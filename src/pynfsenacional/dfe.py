"""Distribuição DF-e — a "caixa postal" do CNPJ no ADN, lida por NSU.

Traz tudo o que está ligado ao CNPJ do certificado: as NFS-e que ele EMITIU (é o prestador),
as que RECEBEU (é o tomador) e os EVENTOS (cancelamento, substituição, manifestação). O NSU
é sequencial e só cresce: guarde o `ultimo_nsu` e passe-o na próxima vez.

Uma página por requisição (~50 documentos, XML embutido com `lote=true`). O ADN limita a
taxa: entre páginas há uma pausa e, no HTTP 429, a MESMA página é pedida de novo com espera
crescente. Se ainda assim parar, `parcial=True` e o `ultimo_nsu` diz até onde chegou — a
chamada seguinte continua dali.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from . import chave as _chave
from .sefin import SefinClient, _descomprimir, _erros, _falha_http, _msg_erros

logger = logging.getLogger("pynfsenacional.dfe")

# StatusProcessamento que encerra a leitura (não há mais o que buscar). O ADN já respondeu
# "NenhumDocumentoLocalizado" e "NENHUM_DOCUMENTO_LOCALIZADO" — compara-se sem caixa nem "_".
STATUS_FIM = ("nenhumdocumentolocalizado",)
# A RECUSA também encerra, mas NÃO é "nada a ler": o ADN não leu a caixa. Medido em produção
# (01/11/2026): consulta por procuração sem a procuração do serviço volta HTTP 400,
# `StatusProcessamento: "REJEICAO"` e `Erros: [{"Codigo": "E2245", "Descricao": "Não há
# procuração da inscrição … para a inscrição …"}]`. Até a 1.2.0 a rejeição encerrava com
# `parcial=False` e `erro=None` — igual a uma caixa vazia.
STATUS_REJEICAO = ("rejeicao",)


def _norm(status: str | None) -> str:
    return (status or "").replace("_", "").lower()


def _fim(status: str | None) -> bool:
    return _norm(status) in STATUS_FIM


def _rejeicao(status: str | None) -> bool:
    return _norm(status) in STATUS_REJEICAO


def prestador_do_xml(xml: str | None) -> str | None:
    """CNPJ (ou CPF) do prestador da NFS-e: o do `<prest>` da DPS; sem ele, o do `<emit>`."""
    if not xml:
        return None
    try:
        raiz = etree.fromstring(xml.encode("utf-8"))
    except etree.XMLSyntaxError:
        return None
    for pai in ("prest", "emit"):
        for el in raiz.iter(f"{{*}}{pai}"):
            for doc in ("CNPJ", "CPF"):
                achado = el.find(f"{{*}}{doc}")
                if achado is not None and (achado.text or "").strip():
                    return _chave.limpar(achado.text or "")
    return None


@dataclass
class DocumentoDfe:
    nsu: int
    tipo_documento: str | None      # "NFSE" | "EVENTO"
    chave_acesso: str | None
    tipo_evento: str | None         # ex.: "CANCELAMENTO" (texto, não código)
    data_hora: str | None
    xml: str | None

    @property
    def evento(self) -> bool:
        return (self.tipo_documento or "").upper() == "EVENTO" or bool(self.tipo_evento)

    def classificar(self, cnpj: str) -> str:
        """"evento", "emitida" (o `cnpj` é o prestador) ou "recebida"."""
        if self.evento:
            return "evento"
        prest = prestador_do_xml(self.xml)
        return "emitida" if prest and prest == _chave.limpar(cnpj) else "recebida"


@dataclass
class RespostaDfe:
    documentos: list[DocumentoDfe] = field(default_factory=list)
    ultimo_nsu: int = 0
    status: str | None = None
    tem_mais: bool = False      # parou no teto de páginas; chame de novo com `ultimo_nsu`
    parcial: bool = False       # parou por erro/limite/recusa; o que veio está em `documentos`
    erro: str | None = None
    rejeitada: bool = False     # o ADN RECUSOU a consulta (ex.: E2245, sem procuração)
    # cada erro da recusa: {codigo, descricao, complemento}
    erros: list[dict[str, str | None]] = field(default_factory=list)


def _documento(bruto: dict[str, Any]) -> DocumentoDfe:
    def g(*nomes: str) -> Any:
        for n in nomes:
            if bruto.get(n) is not None:
                return bruto[n]
        return None

    nsu = g("NSU", "nsu")
    arquivo = g("ArquivoXml", "arquivoXml")
    xml = None
    if isinstance(arquivo, str) and arquivo:
        try:
            xml = _descomprimir(arquivo)
        except Exception:  # noqa: BLE001 — um item ilegível não derruba a página
            logger.warning("DF-e NSU=%s: XML embutido ilegível", nsu)
    ev = g("TipoEvento", "tipoEvento")
    return DocumentoDfe(
        nsu=int(nsu) if str(nsu).isdigit() else 0,
        tipo_documento=g("TipoDocumento", "tipoDocumento"),
        chave_acesso=g("ChaveAcesso", "chaveAcesso"),
        tipo_evento=str(ev) if ev is not None else None,
        data_hora=g("DataHoraGeracao", "dataHoraGeracao", "DataHoraRegistro", "dhProc"),
        xml=xml,
    )


def sincronizar(cliente: SefinClient, cnpj: str, nsu: int = 0, *, max_paginas: int = 20,
                pausa_s: float = 1.0, max_429: int = 5,
                dormir: Callable[[float], None] = time.sleep) -> RespostaDfe:
    """Lê a caixa postal do `cnpj` a partir do `nsu` (exclusivo), até `max_paginas`."""
    if nsu < 0:
        raise ValueError("NSU não pode ser negativo")
    resp = RespostaDfe(ultimo_nsu=nsu)
    tentativas_429 = 0
    pagina = 0
    while pagina < max_paginas:
        try:
            r = cliente.distribuicao_dfe(resp.ultimo_nsu, _chave.limpar(cnpj))
        except Exception as e:  # noqa: BLE001 — rede: devolve o que já veio
            resp.parcial, resp.erro = True, f"{type(e).__name__}: {e}"
            return resp
        if r.status_code == 429 and tentativas_429 < max_429:
            tentativas_429 += 1
            dormir(3.0 * tentativas_429)
            continue
        if r.status_code not in (200, 400, 404):
            resp.parcial, resp.erro = True, _falha_http(r.status_code, "distribuição DF-e")
            return resp
        try:
            dados: dict[str, Any] = r.json()
        except ValueError:
            if r.status_code == 400:
                resp.parcial, resp.erro = True, _falha_http(400, "distribuição DF-e")
            return resp     # corpo vazio = nada a ler
        if not isinstance(dados, dict):
            dados = {}
        status = dados.get("StatusProcessamento") or dados.get("statusProcessamento")
        if _rejeicao(status) or r.status_code == 400:
            # Recusa: não leu a caixa. Guarda o motivo (todos os erros) e para — repetir não
            # muda a resposta, e lida como "nenhum documento" seria um falso negativo.
            resp.status = status
            resp.rejeitada, resp.parcial = True, True
            resp.erros = _erros({"erros": dados.get("Erros") or dados.get("erros")
                                 or dados.get("erro") or []})
            if resp.erros:
                cod = resp.erros[0]["codigo"]
                resp.erro = (f"[{cod}] " if cod else "") + _msg_erros(resp.erros)
            else:
                resp.erro = _falha_http(r.status_code, "distribuição DF-e recusada")
            return resp
        tentativas_429 = 0
        pagina += 1
        resp.status = status
        lote = dados.get("LoteDFe") or dados.get("loteDFe") or []
        for bruto in lote:
            if isinstance(bruto, dict):
                doc = _documento(bruto)
                resp.documentos.append(doc)
                resp.ultimo_nsu = max(resp.ultimo_nsu, doc.nsu)
        if not lote or _fim(resp.status):
            return resp
        if pagina < max_paginas:
            dormir(pausa_s)
    resp.tem_mais = True
    return resp

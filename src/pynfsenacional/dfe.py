"""Distribuição DF-e — a "caixa postal" do CNPJ no ADN, lida por NSU.

Traz tudo o que está ligado ao CNPJ do certificado: as NFS-e que ele EMITIU (é o prestador),
as que RECEBEU (é o tomador) e os EVENTOS (cancelamento, substituição, manifestação). O NSU
é sequencial e só cresce: guarde o `ultimo_nsu` e passe-o na próxima vez.

Uma página por requisição (~50 documentos, XML embutido com `lote=true`). O ADN limita a
taxa: entre páginas há uma pausa e, no HTTP 429, a MESMA página é pedida de novo com espera
crescente. Se ainda assim parar, `parcial=True` e o `ultimo_nsu` diz até onde chegou — a
chamada seguinte continua dali.

Duas peças para quem roda com tempo contado (um processo que outro mata, uma tela esperando):
`prazo_s` é o teto de relógio da sincronização inteira — estourado, devolve o que já veio, com
o `ultimo_nsu` das páginas COMPLETAS (`tem_mais=True`, `prazo_esgotado=True`); e
`ao_receber_pagina` é chamado a cada página, para gravar à medida (se ele falhar, a
sincronização para e o `ultimo_nsu` fica no fim da página anterior).
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

from . import chave as _chave
from .sefin import SefinClient, _descomprimir_bytes, _erros, _falha_http, _msg_erros

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


_RE_ENCODING = re.compile(rb"""^\s*<\?xml[^>]*\bencoding\s*=\s*["']([A-Za-z0-9._-]+)["']""")


def decodificar_xml(dados: bytes) -> str | None:
    """Os bytes de um XML como texto: UTF-8; sem ser UTF-8, a codificação que o próprio XML
    declara no prólogo (ex. ISO-8859-1). None se nenhuma servir."""
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        pass
    m = _RE_ENCODING.match(dados)
    if m:
        try:
            return dados.decode(m.group(1).decode("ascii"))
        except (LookupError, UnicodeDecodeError):
            return None
    return None


def prestador_do_xml(xml: str | bytes | None) -> str | None:
    """CNPJ (ou CPF) do prestador da NFS-e: o do `<prest>` da DPS; sem ele, o do `<emit>`.
    Aceita o texto ou os bytes do XML (os bytes respeitam a codificação declarada)."""
    if not xml:
        return None
    try:
        raiz = etree.fromstring(xml if isinstance(xml, bytes) else xml.encode("utf-8"))
    except (etree.XMLSyntaxError, ValueError):
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
    xml: str | None                 # o XML como texto (UTF-8 ou a codificação declarada)
    # Os bytes do XML como o ADN entregou (descomprimidos). Grave ESTES: o texto de um XML
    # que declara ISO-8859-1, regravado em UTF-8, passa a mentir no prólogo.
    xml_bytes: bytes | None = None
    erro_xml: str | None = None     # por que o XML embutido não pôde ser lido (None = leu)

    @property
    def evento(self) -> bool:
        return (self.tipo_documento or "").upper() == "EVENTO" or bool(self.tipo_evento)

    @property
    def ilegivel(self) -> bool:
        """O item trouxe XML, mas não deu para lê-lo (veja `erro_xml`)."""
        return self.erro_xml is not None

    def classificar(self, cnpj: str) -> str:
        """"evento", "emitida" (o `cnpj` é o prestador) ou "recebida"."""
        if self.evento:
            return "evento"
        prest = prestador_do_xml(self.xml_bytes if self.xml_bytes is not None else self.xml)
        return "emitida" if prest and prest == _chave.limpar(cnpj) else "recebida"

    def nome_arquivo(self) -> str:
        """Um nome de arquivo único na caixa: `<chave>.xml` para a nota e
        `<chave>_ev<NSU>.xml` para o evento. ☠️ O `ChaveAcesso` de um EVENTO é a chave da
        PRÓPRIA nota: com o mesmo nome, o evento apagava a nota (ou outro evento dela) na
        pasta e num ZIP. O NSU é único na caixa; o número sequencial do evento não serve
        (repete entre tipos de evento). Sem chave, `nsu<NSU>.xml`."""
        base = re.sub(r"[^A-Za-z0-9_-]", "", str(self.chave_acesso or ""))
        if not base:
            return f"nsu{self.nsu}.xml"
        return f"{base}_ev{self.nsu}.xml" if self.evento else f"{base}.xml"

    def gravar(self, pasta: str | Path) -> Path | None:
        """Grava os bytes do XML em `pasta/nome_arquivo()` de forma ATÔMICA (temporário na
        mesma pasta + `os.replace`): um processo morto no meio nunca deixa um XML pela
        metade no nome final. Devolve o caminho, ou None quando o item veio sem XML."""
        dados = self.xml_bytes if self.xml_bytes is not None else (
            self.xml.encode("utf-8") if self.xml is not None else None)
        if dados is None:
            return None
        destino = Path(pasta)
        destino.mkdir(parents=True, exist_ok=True)
        final = destino / self.nome_arquivo()
        fd, tmp = tempfile.mkstemp(prefix=f".{final.name}.", suffix=".tmp", dir=destino)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(dados)
            os.replace(tmp, final)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return final


@dataclass
class RespostaDfe:
    documentos: list[DocumentoDfe] = field(default_factory=list)
    ultimo_nsu: int = 0
    status: str | None = None
    tem_mais: bool = False      # parou no teto de páginas/prazo; chame de novo com `ultimo_nsu`
    parcial: bool = False       # parou por erro/limite/recusa; o que veio está em `documentos`
    erro: str | None = None
    rejeitada: bool = False     # o ADN RECUSOU a consulta (ex.: E2245, sem procuração)
    # cada erro da recusa: {codigo, descricao, complemento}
    erros: list[dict[str, str | None]] = field(default_factory=list)
    prazo_esgotado: bool = False   # parou no `prazo_s` (não é erro: chame de novo)
    # NSUs dos itens com XML embutido ilegível — o NSU passa por eles, então alguém decide
    ilegiveis: list[int] = field(default_factory=list)


def _documento(bruto: dict[str, Any]) -> DocumentoDfe:
    def g(*nomes: str) -> Any:
        for n in nomes:
            if bruto.get(n) is not None:
                return bruto[n]
        return None

    nsu = g("NSU", "nsu")
    arquivo = g("ArquivoXml", "arquivoXml")
    xml = dados = erro = None
    if isinstance(arquivo, str) and arquivo:
        try:
            dados = _descomprimir_bytes(arquivo)
        except Exception as e:  # noqa: BLE001 — um item ilegível não derruba a página
            erro = f"XML embutido ilegível ({type(e).__name__})"
        else:
            xml = decodificar_xml(dados)
            if xml is None:
                erro = "XML embutido em codificação desconhecida (os bytes estão em xml_bytes)"
        if erro:
            logger.warning("DF-e NSU=%s: %s", nsu, erro)
    elif arquivo not in (None, ""):
        erro = f"ArquivoXml inesperado ({type(arquivo).__name__})"
    ev = g("TipoEvento", "tipoEvento")
    return DocumentoDfe(
        nsu=int(nsu) if str(nsu).isdigit() else 0,
        tipo_documento=g("TipoDocumento", "tipoDocumento"),
        chave_acesso=g("ChaveAcesso", "chaveAcesso"),
        tipo_evento=str(ev) if ev is not None else None,
        data_hora=g("DataHoraGeracao", "dataHoraGeracao", "DataHoraRegistro", "dhProc"),
        xml=xml,
        xml_bytes=dados,
        erro_xml=erro,
    )


def sincronizar(cliente: SefinClient, cnpj: str, nsu: int = 0, *, max_paginas: int = 20,
                pausa_s: float = 1.0, max_429: int = 5,
                dormir: Callable[[float], None] = time.sleep,
                prazo_s: float | None = None,
                ao_receber_pagina: Callable[[list[DocumentoDfe], int], None] | None = None,
                relogio: Callable[[], float] = time.monotonic) -> RespostaDfe:
    """Lê a caixa postal do `cnpj` a partir do `nsu` (exclusivo), até `max_paginas`.

    `prazo_s`: teto de RELÓGIO da sincronização inteira (None = sem teto). Nenhuma requisição
    nem espera começa se não couber no que resta; cada requisição leva o que resta como teto
    (`SefinClient.distribuicao_dfe(prazo_s=…)`). Estourado, devolve o que já veio, com
    `tem_mais=True` e `prazo_esgotado=True` — o `ultimo_nsu` é o das páginas completas, então
    a chamada seguinte continua dali sem pular nada.

    `ao_receber_pagina(documentos, ultimo_nsu)`: chamado a cada página lida, ANTES de ela
    entrar no `ultimo_nsu` devolvido — para gravar à medida. Se ele levantar, a sincronização
    para com `parcial=True` e o erro, a página sai de `documentos` e o `ultimo_nsu` fica no
    fim da página anterior (nada se perde: a próxima chamada a relê).

    `relogio` e `dormir` são injetáveis (teste)."""
    if nsu < 0:
        raise ValueError("NSU não pode ser negativo")
    limite = relogio() + prazo_s if prazo_s is not None else None
    resp = RespostaDfe(ultimo_nsu=nsu)

    def resta() -> float | None:
        return None if limite is None else limite - relogio()

    def esgotou(espera: float = 0.0) -> bool:
        r = resta()
        if r is None or r > espera:
            return False
        resp.tem_mais = resp.prazo_esgotado = True
        logger.info("DF-e: prazo de %ss esgotado — para no NSU %s", prazo_s, resp.ultimo_nsu)
        return True

    tentativas_429 = 0
    pagina = 0
    while pagina < max_paginas:
        if esgotou():
            return resp
        try:
            restante = resta()
            if restante is None:
                r = cliente.distribuicao_dfe(resp.ultimo_nsu, _chave.limpar(cnpj))
            else:
                r = cliente.distribuicao_dfe(resp.ultimo_nsu, _chave.limpar(cnpj),
                                             prazo_s=restante)
        except Exception as e:  # noqa: BLE001 — rede: devolve o que já veio
            if limite is not None and relogio() >= limite:
                resp.tem_mais = resp.prazo_esgotado = True
                return resp
            resp.parcial, resp.erro = True, f"{type(e).__name__}: {e}"
            return resp
        if r.status_code == 429 and tentativas_429 < max_429:
            tentativas_429 += 1
            espera = 3.0 * tentativas_429
            if esgotou(espera):
                return resp
            dormir(espera)
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
        docs = [_documento(b) for b in lote if isinstance(b, dict)]
        ultimo = max([resp.ultimo_nsu, *(d.nsu for d in docs)])
        if ao_receber_pagina is not None and docs:
            try:
                ao_receber_pagina(docs, ultimo)
            except Exception as e:  # noqa: BLE001 — a gravação falhou: para no consistente
                resp.parcial = True
                resp.erro = f"a página não foi gravada ({type(e).__name__}: {e})"
                return resp
        resp.documentos.extend(docs)
        resp.ilegiveis.extend(d.nsu for d in docs if d.ilegivel)
        resp.ultimo_nsu = ultimo
        if not lote or _fim(resp.status):
            return resp
        if pagina < max_paginas:
            if esgotou(pausa_s):
                return resp
            dormir(pausa_s)
    resp.tem_mais = True
    return resp

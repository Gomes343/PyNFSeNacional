"""Orquestração da emissão: junta config → DPS → assinatura → transporte → DANFSe.

É a API pública (`Emissor`) e o resultado (`Nota`). O pipeline está completo; cada
etapa delega ao módulo especializado (config/dps/assinatura/sefin/danfse). Também
consulta a nota pela chave, cancela (eventos) e lê a caixa postal DF-e do CNPJ.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from lxml import etree

from . import assinatura, dfe, dps, eventos, sefin
from . import chave as _chave
from .config import ClienteConfig, ConfigError, validar_retencao, validar_tomador

# A lib só EMITE logs; quem configura handler/nível é a aplicação (a CLI faz no --verbose).
# Nunca logamos a senha do .pfx nem o XML com dados do tomador — só Id, ambiente, E-code, nNFSe.
logger = logging.getLogger("pynfsenacional.emissor")

# Quantos nDPS o contador pode pular, numa emissão, por estarem tomados por OUTRAS notas.
MAX_NUMEROS_PULADOS = 20


@dataclass
class Nota:
    """Resultado de uma emissão (compatível em espírito com o ResultadoEmissao da
    referência). `emitida` é a fonte da verdade."""
    status: str                       # "ok" | "ja_emitida" | "erro"
    emitida: bool
    id_cliente: str
    numero_nfse: str | None = None
    chave_acesso: str | None = None
    nfse_xml: str | None = None
    xml_path: str | None = None
    pdf_path: str | None = None
    id_dps: str | None = None
    erro_msg: str | None = None
    erros: list[dict[str, str | None]] = field(default_factory=list)   # todos os E-codes
    alertas: list[str] = field(default_factory=list)

    def danfse(self, destino: str | Path) -> str:
        """Gera o PDF do DANFSe a partir do XML desta nota."""
        from . import danfse as _danfse
        if not self.nfse_xml:
            raise ValueError("nota sem XML da NFS-e — nada para renderizar")
        self.pdf_path = _danfse.render(self.nfse_xml, destino)
        return self.pdf_path


@dataclass
class ResultadoEvento:
    """Resultado de um pedido de cancelamento. `ok` = a SEFIN registrou o evento."""
    ok: bool
    chave_acesso: str
    modo: str                         # "direto" (e101101) | "analise" (e101103)
    cancelada: bool = False           # True só no direto: a análise espera o município
    evento_xml: str | None = None
    erro_codigo: str | None = None
    erro_msg: str | None = None
    erros: list[dict[str, str | None]] = field(default_factory=list)


def _doc(tomador: dict[str, Any] | None) -> str:
    if not tomador:
        return ""
    return _chave.limpar(str(tomador.get("cpf_cnpj") or tomador.get("documento") or ""))


def mesma_nota(nfse_xml: str | None, valor: Any, tomador: dict[str, Any] | None) -> bool | None:
    """A NFS-e de `nfse_xml` é a nota que se está pedindo agora? Compara VALOR e DOCUMENTO
    do tomador — descrição fica de fora de propósito (reescrevê-la num reenvio não faz dela
    outra nota). None = não deu para conferir."""
    if not nfse_xml:
        return None
    try:
        raiz = etree.fromstring(nfse_xml.encode("utf-8"))
    except etree.XMLSyntaxError:
        return None
    v = raiz.find(".//{*}vServ")
    if v is None or not (v.text or "").strip():
        return None
    if Decimal(v.text.strip()) != dps.valor_decimal(valor):
        return False
    toma = raiz.find(".//{*}toma")
    doc_xml = ""
    if toma is not None:
        for tag in ("CNPJ", "CPF", "NIF"):
            el = toma.find(f"{{*}}{tag}")
            if el is not None and el.text:
                doc_xml = _chave.limpar(el.text)
                break
    return doc_xml == _doc(tomador)


class Emissor:
    """Ponto de entrada. `Emissor("config/cliente.json").emitir(...)`."""

    def __init__(self, config: str | Path | ClienteConfig, ambiente: str | None = None,
                 out_dir: str | Path = "out"):
        self.cfg = config if isinstance(config, ClienteConfig) else ClienteConfig.from_json(config)
        self.ambiente = ambiente or self.cfg.ambiente
        self.out_dir = Path(out_dir)

    def emitir(self, *, valor: Decimal | float | int | str, descricao: str,
               tomador: dict[str, Any] | None = None,
               numero: str | None = None, serie: str = "1") -> Nota:
        """Emite uma NFS-e. Pipeline (cada etapa é um módulo):
            1. montar a DPS (dps.montar_dps)        — lógica fiscal
            2. assinar (assinatura.assinar_dps)     — XMLDSIG
            3. idempotência + envio (sefin)         — mTLS
            4. (opcional) nota.danfse(path)         — PDF local
        `valor`: Decimal (recomendado), str ("1.262,90" ou "1262.90"), int ou float.
        `numero` (nDPS): se None, usa o contador do ambiente.

        Antes de montar a DPS, valida config + tomador (E-codes determinísticos) e
        levanta `ConfigError` — não adianta assinar/enviar uma DPS que o SEFIN vai rejeitar.
        """
        problemas = (self.cfg.validar() + validar_tomador(tomador)
                     + validar_retencao(self.cfg, tomador))   # E0204/E0237 (§15)
        if self.ambiente not in ("homologacao", "producao"):
            problemas.append(
                f"ambiente inválido: {self.ambiente!r} (use 'homologacao' ou 'producao')"
            )
        try:
            if dps.valor_decimal(valor) <= 0:
                problemas.append("valor do serviço deve ser maior que zero")
        except ValueError as e:
            problemas.append(str(e))
        if problemas:
            raise ConfigError("config inválida para emissão:\n  - " + "\n  - ".join(problemas))

        do_contador = numero is None
        numero = numero or self._proximo_numero()
        cliente = self._sefin_client()

        # Idempotência: se a DPS já foi emitida, não reemite — recupera a nota (§5).
        for _ in range(MAX_NUMEROS_PULADOS + 1):
            idd = dps.id_dps(self.cfg, numero, serie)
            logger.info("emitindo id_cliente=%s ambiente=%s nDPS=%s idDps=%s",
                        self.cfg.id, self.ambiente, numero, idd)
            if not cliente.verificar_dps(idd):
                break
            chave = cliente.consultar_dps(idd)
            xml = self._buscar_xml(cliente, chave)
            if do_contador:
                # ☠️ Até a 1.1.0 o contador NÃO andava aqui: depois de um envio sem resposta,
                # toda emissão seguinte caía nesta DPS e voltava "já emitida", para sempre.
                self._commit_numero(numero)
                if mesma_nota(xml, valor, tomador) is False:
                    # O número está tomado por OUTRA nota (contador atrasado) → o próximo.
                    logger.warning("nDPS %s já é de outra nota (chave=%s) — pulando", numero, chave)
                    numero = self._proximo_numero()
                    continue
            return self._nota_recuperada(idd, chave, xml)
        else:
            raise ConfigError(f"o contador de nDPS está {MAX_NUMEROS_PULADOS}+ números atrás das "
                              f"notas já emitidas — ajuste {self._contador_path()}")

        xml = dps.montar_dps(self.cfg, numero=numero, valor=valor, descricao=descricao,
                             tomador=tomador, ambiente=self.ambiente, serie=serie)
        xml_assinado = assinatura.assinar_dps(
            xml, cert_pfx_path=self.cfg.certificado.path, senha=self.cfg.certificado.senha,
        )
        resp = cliente.emitir(xml_assinado)

        if resp.ok:                       # incrementa o contador SÓ após emissão confirmada
            self._commit_numero(numero)
            logger.info("emitida: nNFSe=%s chave=%s", resp.numero_nfse, resp.chave_acesso)
        else:
            logger.warning("falha na emissão idDps=%s: [%s] %s",
                           idd, resp.erro_codigo, resp.erro_msg)
        return Nota(
            status="ok" if resp.ok else "erro",
            emitida=resp.ok,
            id_cliente=self.cfg.id,
            numero_nfse=resp.numero_nfse or (_chave.numero_da_chave(resp.chave_acesso)
                                             if resp.ok else None),
            chave_acesso=resp.chave_acesso,
            nfse_xml=resp.nfse_xml,
            id_dps=idd,
            erro_msg=(f"[{resp.erro_codigo}] {resp.erro_msg}"
                      if resp.erro_codigo else resp.erro_msg),
            erros=resp.erros,
            alertas=resp.alertas,
        )

    def consultar(self, chave: str) -> Nota | None:
        """A NFS-e da `chave`, com o XML (para o DANFSe); None se a chave não existe."""
        ch = _chave.limpar(chave)
        xml = self._sefin_client().consultar_nfse(ch)
        if xml is None:
            return None
        return Nota(status="ok", emitida=True, id_cliente=self.cfg.id, chave_acesso=ch,
                    nfse_xml=xml, numero_nfse=self._numero(xml, ch))

    def cancelar(self, chave: str, *, justificativa: str, motivo: int = 1,
                 modo: str = "direto") -> ResultadoEvento:
        """Cancela a NFS-e (`modo="direto"`, e101101) ou pede a análise fiscal do
        cancelamento (`modo="analise"`, e101103 — para municípios que não aceitam o direto).

        `motivo`: 1=Erro na Emissão · 2=Serviço não Prestado · 9=Outros. `justificativa`:
        15 a 200 caracteres. Valida antes de assinar e levanta `ConfigError`."""
        if self.ambiente not in ("homologacao", "producao"):
            raise ConfigError(f"ambiente inválido: {self.ambiente!r}")
        ch = _chave.limpar(chave)
        xml = eventos.montar_cancelamento(
            chave=ch, autor=self.cfg.prestador.cnpj, motivo=motivo,
            justificativa=justificativa, ambiente=self.ambiente, modo=modo,
        )
        assinado = assinatura.assinar_xml(xml, "infPedReg",
                                          cert_pfx_path=self.cfg.certificado.path,
                                          senha=self.cfg.certificado.senha)
        logger.info("cancelando id_cliente=%s ambiente=%s modo=%s", self.cfg.id,
                    self.ambiente, modo)
        r = self._sefin_client().registrar_evento(ch, assinado)
        if not r.ok:
            logger.warning("evento recusado: [%s] %s", r.erro_codigo, r.erro_msg)
        return ResultadoEvento(
            ok=r.ok, chave_acesso=ch, modo=modo, cancelada=r.ok and modo == "direto",
            evento_xml=r.evento_xml, erro_codigo=r.erro_codigo,
            erro_msg=(f"[{r.erro_codigo}] {r.erro_msg}" if r.erro_codigo else r.erro_msg),
            erros=r.erros,
        )

    def sincronizar_dfe(self, nsu: int = 0, *, max_paginas: int = 20) -> dfe.RespostaDfe:
        """Lê a caixa postal DF-e do CNPJ do prestador a partir do `nsu` (guarde o
        `ultimo_nsu` da resposta para a próxima vez). Ver `dfe.sincronizar`."""
        return dfe.sincronizar(self._sefin_client(), self.cfg.prestador.cnpj, nsu,
                               max_paginas=max_paginas)

    # ── internos ──────────────────────────────────────────────────────────────
    def _nota_recuperada(self, idd: str, chave: str | None, xml: str | None) -> Nota:
        logger.info("DPS %s já emitida — recuperada chave=%s (não reemite)", idd, chave)
        erro = None
        if not chave:
            erro = ("DPS já emitida, mas a chave não pôde ser recuperada — "
                    "consulte a nota no portal")
            logger.warning("DPS %s já emitida, mas consultar_dps não devolveu a chave", idd)
        return Nota(status="ja_emitida", emitida=True, id_cliente=self.cfg.id,
                    chave_acesso=chave, nfse_xml=xml, numero_nfse=self._numero(xml, chave),
                    id_dps=idd, erro_msg=erro)

    @staticmethod
    def _numero(xml: str | None, chave: str | None) -> str | None:
        return (sefin._tag(xml, "nNFSe") if xml else None) or _chave.numero_da_chave(chave)

    @staticmethod
    def _buscar_xml(cliente: sefin.SefinClient, chave: str | None) -> str | None:
        """O XML da nota recuperada — sem ele não há DANFSe. Melhor esforço: falhar aqui
        não muda o fato de a nota existir."""
        if not chave:
            return None
        try:
            return cliente.consultar_nfse(chave)
        except Exception as e:  # noqa: BLE001
            logger.warning("nota %s existe, mas o XML não veio: %s", chave, e)
            return None

    def _contador_path(self) -> Path:
        return self.out_dir / f"numero_{self.cfg.id}_{self.ambiente}.txt"

    def _proximo_numero(self) -> str:
        """Próximo nDPS por ambiente (docs/conhecimento-fiscal.md §5). nDPS é só um
        contador INTERNO (≠ nNFSe, que o SEFIN atribui). Lê o contador persistido ou,
        na primeira vez, a semente `dados_nota.numero`. O incremento só acontece após
        emissão confirmada ou DPS achada na SEFIN (`_commit_numero`)."""
        arq = self._contador_path()
        if arq.exists():
            txt = arq.read_text(encoding="utf-8").strip()
            if txt:
                return txt
        return str(self.cfg.dados_nota.get("numero", "1"))

    def _commit_numero(self, numero: str) -> None:
        """Persiste o PRÓXIMO nDPS (numero+1), sem nunca recuar o contador."""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        try:
            proximo = int(numero) + 1
            atual = self._proximo_numero()
            if atual.isdigit():
                proximo = max(proximo, int(atual))
            texto = str(proximo)
        except ValueError:
            texto = numero
        self._contador_path().write_text(texto, encoding="utf-8")

    def _sefin_client(self) -> sefin.SefinClient:
        return sefin.SefinClient(
            ambiente=self.ambiente,
            cert_pfx_path=self.cfg.certificado.path,
            senha=self.cfg.certificado.senha,
            codigo_municipio=self.cfg.prestador.codigo_municipio,
        )

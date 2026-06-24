"""Orquestração da emissão: junta config → DPS → assinatura → transporte → DANFSe.

É a API pública (`Emissor`) e o resultado (`Nota`). O pipeline está completo; cada
etapa delega ao módulo especializado (config/dps/assinatura/sefin/danfse).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import assinatura, dps, sefin
from .config import ClienteConfig, ConfigError, validar_tomador

# A lib só EMITE logs; quem configura handler/nível é a aplicação (a CLI faz no --verbose).
# Nunca logamos a senha do .pfx nem o XML com dados do tomador — só Id, ambiente, E-code, nNFSe.
logger = logging.getLogger("pynfsenacional.emissor")


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

    def danfse(self, destino: str | Path) -> str:
        """Gera o PDF do DANFSe a partir do XML desta nota."""
        from . import danfse as _danfse
        if not self.nfse_xml:
            raise ValueError("nota sem XML da NFS-e — nada para renderizar")
        self.pdf_path = _danfse.render(self.nfse_xml, destino)
        return self.pdf_path


class Emissor:
    """Ponto de entrada. `Emissor("config/cliente.json").emitir(...)`."""

    def __init__(self, config: str | Path | ClienteConfig, ambiente: str | None = None,
                 out_dir: str | Path = "out"):
        self.cfg = config if isinstance(config, ClienteConfig) else ClienteConfig.from_json(config)
        self.ambiente = ambiente or self.cfg.ambiente
        self.out_dir = Path(out_dir)

    def emitir(self, *, valor: float, descricao: str,
               tomador: dict[str, Any] | None = None,
               numero: str | None = None, serie: str = "1") -> Nota:
        """Emite uma NFS-e. Pipeline (cada etapa é um módulo):
            1. montar a DPS (dps.montar_dps)        — lógica fiscal
            2. assinar (assinatura.assinar_dps)     — XMLDSIG
            3. idempotência + envio (sefin)         — mTLS
            4. (opcional) nota.danfse(path)         — PDF local
        `numero` (nDPS): se None, usa o contador do ambiente.

        Antes de montar a DPS, valida config + tomador (E-codes determinísticos) e
        levanta `ConfigError` — não adianta assinar/enviar uma DPS que o SEFIN vai rejeitar.
        """
        problemas = self.cfg.validar() + validar_tomador(tomador)
        if self.ambiente not in ("homologacao", "producao"):
            problemas.append(
                f"ambiente inválido: {self.ambiente!r} (use 'homologacao' ou 'producao')"
            )
        if problemas:
            raise ConfigError("config inválida para emissão:\n  - " + "\n  - ".join(problemas))

        numero = numero or self._proximo_numero()
        idd = dps.id_dps(self.cfg, numero, serie)
        cliente = self._sefin_client()
        logger.info("emitindo id_cliente=%s ambiente=%s nDPS=%s idDps=%s",
                    self.cfg.id, self.ambiente, numero, idd)

        # Idempotência: se a DPS já foi emitida, não reemite — recupera a chave (§5).
        if cliente.verificar_dps(idd):
            chave = cliente.consultar_dps(idd)
            logger.info("DPS %s já emitida — recuperada chave=%s (não reemite)", idd, chave)
            erro = None
            if not chave:
                erro = ("DPS já emitida, mas a chave não pôde ser recuperada — "
                        "consulte a nota no portal")
                logger.warning("DPS %s já emitida, mas consultar_dps não devolveu a chave", idd)
            return Nota(status="ja_emitida", emitida=True, id_cliente=self.cfg.id,
                        chave_acesso=chave, id_dps=idd, erro_msg=erro)

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
            numero_nfse=resp.numero_nfse,
            chave_acesso=resp.chave_acesso,
            nfse_xml=resp.nfse_xml,
            id_dps=idd,
            erro_msg=(f"[{resp.erro_codigo}] {resp.erro_msg}"
                      if resp.erro_codigo else resp.erro_msg),
        )

    # ── internos ──────────────────────────────────────────────────────────────
    def _contador_path(self) -> Path:
        return self.out_dir / f"numero_{self.cfg.id}_{self.ambiente}.txt"

    def _proximo_numero(self) -> str:
        """Próximo nDPS por ambiente (docs/conhecimento-fiscal.md §5). nDPS é só um
        contador INTERNO (≠ nNFSe, que o SEFIN atribui). Lê o contador persistido ou,
        na primeira vez, a semente `dados_nota.numero`. O incremento só acontece após
        emissão confirmada (`_commit_numero`, chamado no transporte — Fase 5)."""
        arq = self._contador_path()
        if arq.exists():
            txt = arq.read_text(encoding="utf-8").strip()
            if txt:
                return txt
        return str(self.cfg.dados_nota.get("numero", "1"))

    def _commit_numero(self, numero: str) -> None:
        """Persiste o PRÓXIMO nDPS (numero+1). Chamado só após emissão confirmada."""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        try:
            proximo = str(int(numero) + 1)
        except ValueError:
            proximo = numero
        self._contador_path().write_text(proximo, encoding="utf-8")

    def _sefin_client(self) -> sefin.SefinClient:
        return sefin.SefinClient(
            ambiente=self.ambiente,
            cert_pfx_path=self.cfg.certificado.path,
            senha=self.cfg.certificado.senha,
            codigo_municipio=self.cfg.prestador.codigo_municipio,
        )

"""Transporte ao SEFIN Nacional (mTLS). Lib: `requests` + `requests-pkcs12` + código próprio.

★ A peça que NÃO existe pronta em Python para o padrão nacional — é o que este projeto
agrega. Protocolo (portado de uma implementação de referência em PHP, privada):
  • mTLS com o certificado A1 do emitente — **PKCS#12 direto** (como o cURL P12 do PHP),
    sem converter para PEM. Servidor SEM verificação de cadeia (verify=False, igual ao PHP
    `SSL_VERIFYPEER=0` — o endpoint do SEFIN não valida na cadeia padrão).
  • Empacotamento: `gzip + base64` do XML assinado, no campo `dpsXmlGZipB64`.
  • `POST {base}/nfse` → resposta JSON `{chaveAcesso, nfseXmlGZipB64, erros, alertas, ...}`.
  • Idempotência: `HEAD {base}/dps/{id}` (200=existe, 404=não) + `GET {base}/dps/{id}`.

Endpoints (docs/conhecimento-fiscal.md §1):
  • produção:    https://sefin.nfse.gov.br/SefinNacional
  • homologação: https://sefin.producaorestrita.nfse.gov.br/SefinNacional
"""

from __future__ import annotations

import base64
import gzip
import logging
import re
import warnings
from dataclasses import dataclass, field
from typing import Any

import requests
import urllib3
from requests_pkcs12 import Pkcs12Adapter

# Logamos status/contexto, NUNCA o payload (XML com dados do tomador) nem a senha do .pfx.
logger = logging.getLogger("pynfsenacional.sefin")

ENDPOINTS = {
    "producao": "https://sefin.nfse.gov.br/SefinNacional",
    "homologacao": "https://sefin.producaorestrita.nfse.gov.br/SefinNacional",
}

# Overrides de endpoint por município (IBGE) — ex.: Catanduva tem ambiente próprio.
ENDPOINTS_MUNICIPIO: dict[str, dict[str, str]] = {
    "3511102": {
        "producao": "https://164.152.60.237/nota/nacional",
        "homologacao": "https://catanduva.prefeitura.rlz.com.br/nota/nacional",
    },
}


@dataclass
class RespostaSefin:
    ok: bool
    nfse_xml: str | None = None
    chave_acesso: str | None = None
    numero_nfse: str | None = None
    ja_emitida: bool = False        # idempotência: a DPS já tinha sido emitida
    erro_codigo: str | None = None  # ex.: "E0312"
    erro_msg: str | None = None
    alertas: list[str] = field(default_factory=list)
    raw: str | None = None          # corpo bruto da resposta (diagnóstico)


def resolver_endpoint(ambiente: str, codigo_municipio: str | None = None) -> str:
    """Resolve a base URL do SEFIN por ambiente, com override por município (IBGE)."""
    if ambiente not in ENDPOINTS:
        raise ValueError(f"ambiente inválido: {ambiente!r} (use 'homologacao' ou 'producao')")
    if codigo_municipio and codigo_municipio in ENDPOINTS_MUNICIPIO:
        return ENDPOINTS_MUNICIPIO[codigo_municipio][ambiente]
    return ENDPOINTS[ambiente]


def _descomprimir(b64: str) -> str:
    """base64 → gzip → XML (campo *XmlGZipB64 do SEFIN)."""
    return gzip.decompress(base64.b64decode(b64)).decode("utf-8")


def _tag(xml: str, nome: str) -> str | None:
    m = re.search(rf"<{nome}[^>]*>([^<]*)</{nome}>", xml)
    return (m.group(1).strip() or None) if m else None


def _texto_msg(m: dict[str, Any]) -> str | None:
    """Texto de uma mensagem do SEFIN (alterna descricao/Descricao/mensagem/Mensagem)."""
    return m.get("descricao") or m.get("Descricao") or m.get("mensagem") or m.get("Mensagem")


class SefinClient:
    """Cliente HTTP do SEFIN Nacional autenticado por certificado A1 (mTLS)."""

    def __init__(self, *, ambiente: str, cert_pfx_path: str, senha: str,
                 codigo_municipio: str | None = None, timeout: int = 60,
                 verificar_servidor: bool = False):
        self.base_url = resolver_endpoint(ambiente, codigo_municipio).rstrip("/")
        self.timeout = timeout
        self.verificar_servidor = verificar_servidor
        self._sessao = requests.Session()
        # mTLS com o .pfx DIRETO (PKCS#12), como o cURL P12 da referência PHP.
        with warnings.catch_warnings():
            # .pfx ICP-Brasil costuma ser BER (não DER) — a leitura funciona; só silencia o aviso.
            warnings.filterwarnings("ignore", message=".*could not be parsed as DER.*")
            self._sessao.mount(
                "https://", Pkcs12Adapter(pkcs12_filename=cert_pfx_path, pkcs12_password=senha)
            )

    def _req(self, metodo: str, caminho: str, **kw: Any) -> requests.Response:
        with warnings.catch_warnings():
            if not self.verificar_servidor:
                # espelha SSL_VERIFYPEER=0 do PHP; silencia o aviso SÓ aqui — catch_warnings
                # restaura o filtro global do processo do consumidor ao sair.
                warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            return self._sessao.request(
                metodo, f"{self.base_url}/{caminho}",
                timeout=self.timeout, verify=self.verificar_servidor, **kw,
            )

    def verificar_dps(self, id_dps: str) -> bool:
        """HEAD /dps/{id} — True se a DPS já foi emitida (200), False se não (404)."""
        r = self._req("HEAD", f"dps/{id_dps}")
        if r.status_code == 200:
            return True
        if r.status_code == 404:
            return False
        raise RuntimeError(f"verificarDps falhou: HTTP {r.status_code}")

    def consultar_dps(self, id_dps: str) -> str | None:
        """GET /dps/{id} → chave de acesso da NFS-e (se a DPS já gerou nota)."""
        r = self._req("GET", f"dps/{id_dps}", headers={"Accept": "application/json"})
        if r.status_code != 200:
            return None
        try:
            chave = r.json().get("chaveAcesso")
        except ValueError:
            return None
        return chave if isinstance(chave, str) else None

    def emitir(self, xml_dps_assinado: str) -> RespostaSefin:
        """gzip+base64 → POST /nfse (mTLS) → parse da NFS-e. Mapeia E-codes em erro_codigo."""
        payload = base64.b64encode(gzip.compress(xml_dps_assinado.encode("utf-8"))).decode()
        logger.info("POST %s/nfse (%d bytes de DPS assinado)", self.base_url,
                    len(xml_dps_assinado))
        r = self._req(
            "POST", "nfse",
            json={"dpsXmlGZipB64": payload},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        logger.info("SEFIN respondeu HTTP %d (%d bytes)", r.status_code, len(r.text))
        return self._parsear(r)

    def _parsear(self, r: requests.Response) -> RespostaSefin:
        bruto = r.text
        try:
            dados: dict[str, Any] = r.json()
        except ValueError:
            return RespostaSefin(ok=False, erro_msg=f"resposta não-JSON (HTTP {r.status_code})",
                                 raw=bruto)

        # Erros: o SEFIN alterna `erros`/`erro` e Maiúsc/minúsc nos subcampos.
        erros = dados.get("erros") or dados.get("erro") or []
        if erros:
            e0 = erros[0]
            codigo = e0.get("codigo") or e0.get("Codigo")
            desc = _texto_msg(e0)
            compl = e0.get("complemento") or e0.get("Complemento")
            msg = " — ".join(p for p in (desc, compl) if p)
            return RespostaSefin(ok=False, erro_codigo=codigo, erro_msg=msg or "erro na emissão",
                                 raw=bruto)

        b64 = dados.get("nfseXmlGZipB64")
        if not b64:
            if r.status_code >= 500:
                return RespostaSefin(ok=False, erro_msg=f"SEFIN HTTP {r.status_code}", raw=bruto)
            return RespostaSefin(ok=False, erro_msg="resposta sem XML da NFS-e", raw=bruto)

        nfse_xml = _descomprimir(b64)
        alertas = [_texto_msg(a) for a in (dados.get("alertas") or [])]
        return RespostaSefin(
            ok=True,
            nfse_xml=nfse_xml,
            chave_acesso=dados.get("chaveAcesso") or _tag(nfse_xml, "chNFSe"),
            numero_nfse=_tag(nfse_xml, "nNFSe"),
            alertas=[a for a in alertas if a],
            raw=bruto,
        )

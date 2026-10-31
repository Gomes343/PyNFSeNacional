"""Transporte ao SEFIN Nacional (mTLS). Lib: `requests` + `requests-pkcs12` + código próprio.

★ A peça que NÃO existe pronta em Python para o padrão nacional — é o que este projeto
agrega. Protocolo (portado de uma implementação de referência em PHP, privada):
  • mTLS com o certificado A1 do emitente — **PKCS#12 direto** (como o cURL P12 do PHP),
    sem converter para PEM.
  • O certificado do SERVIDOR é conferido (cadeia pública, GlobalSign — medido em 31/10/2026
    nos dois ambientes). Só os endpoints próprios de município (`ENDPOINTS_MUNICIPIO`) seguem
    sem conferência por padrão: um deles é um IP cru, que nenhum certificado cobre.
  • Empacotamento: `gzip + base64` do XML assinado, no campo `dpsXmlGZipB64`.
  • `POST {base}/nfse` → resposta JSON `{chaveAcesso, nfseXmlGZipB64, erros, alertas, ...}`.
  • Idempotência: `HEAD {base}/dps/{id}` (200=existe, 404=não) + `GET {base}/dps/{id}`.
  • Consulta da nota pela chave: `GET {base}/nfse/{chave}` → `nfseXmlGZipB64`.
  • Eventos (cancelamento): `POST {base}/nfse/{chave}/eventos` com `pedidoRegistroEventoXmlGZipB64`.
  • Distribuição DF-e (ADN): `GET {adn}/contribuintes/DFe/{NSU}?cnpjConsulta=…&lote=true`.

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

# Ambiente de Dados Nacional — a "caixa postal" de documentos do CNPJ (distribuição DF-e).
ENDPOINTS_ADN = {
    "producao": "https://adn.nfse.gov.br",
    "homologacao": "https://adn.producaorestrita.nfse.gov.br",
}

# Overrides de endpoint por município (IBGE) — ex.: Catanduva tem ambiente próprio.
ENDPOINTS_MUNICIPIO: dict[str, dict[str, str]] = {
    "3511102": {
        "producao": "https://164.152.60.237/nota/nacional",
        "homologacao": "https://catanduva.prefeitura.rlz.com.br/nota/nacional",
    },
}

# O que cada HTTP sem E-code quer dizer, para quem lê a mensagem (e não o código).
FALHAS_HTTP = {
    401: "acesso recusado — costuma ser o certificado A1 (vencido ou de outro CNPJ)",
    403: "acesso recusado — costuma ser o certificado A1 (vencido ou de outro CNPJ)",
    429: "requisições demais — aguarde um pouco e tente de novo",
    500: "erro interno da SEFIN",
    502: "SEFIN fora do ar (gateway)",
    503: "SEFIN fora do ar (serviço indisponível)",
    504: "SEFIN fora do ar (tempo esgotado no gateway)",
}


def explicar_http(status: int | None) -> str | None:
    """Uma falha HTTP dita para gente — ou None se o status não tem explicação conhecida."""
    return FALHAS_HTTP.get(status) if status else None


@dataclass
class RespostaSefin:
    ok: bool
    nfse_xml: str | None = None
    chave_acesso: str | None = None
    numero_nfse: str | None = None
    ja_emitida: bool = False        # idempotência: a DPS já tinha sido emitida
    erro_codigo: str | None = None  # ex.: "E0312" (o PRIMEIRO, quando vêm vários)
    erro_msg: str | None = None     # texto do primeiro + os demais como "| [E0xxx] …"
    # todos os erros: {codigo, descricao, complemento}
    erros: list[dict[str, str | None]] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)
    http_status: int | None = None
    raw: str | None = None          # corpo bruto da resposta (diagnóstico)


@dataclass
class RespostaEvento:
    ok: bool
    evento_xml: str | None = None   # o evento registrado, como a SEFIN devolve
    erro_codigo: str | None = None
    erro_msg: str | None = None
    erros: list[dict[str, str | None]] = field(default_factory=list)
    http_status: int | None = None
    raw: str | None = None


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


def _comprimir(xml: str) -> str:
    """XML → gzip → base64 (o inverso de `_descomprimir`)."""
    return base64.b64encode(gzip.compress(xml.encode("utf-8"))).decode()


def _tag(xml: str, nome: str) -> str | None:
    m = re.search(rf"<{nome}[^>]*>([^<]*)</{nome}>", xml)
    return (m.group(1).strip() or None) if m else None


def _texto_msg(m: dict[str, Any]) -> str | None:
    """Texto de uma mensagem do SEFIN (alterna descricao/Descricao/mensagem/Mensagem)."""
    return m.get("descricao") or m.get("Descricao") or m.get("mensagem") or m.get("Mensagem")


def _erros(dados: dict[str, Any]) -> list[dict[str, str | None]]:
    """Todas as mensagens de erro da resposta. O SEFIN alterna `erros`/`erro` (e a emissão e
    o evento às vezes mandam um objeto só, não uma lista) e Maiúsc/minúsc nos subcampos."""
    brutos = dados.get("erros") or dados.get("erro") or []
    if isinstance(brutos, dict):
        brutos = [brutos]
    erros: list[dict[str, str | None]] = []
    for e in brutos:
        if not isinstance(e, dict):
            continue
        erros.append({
            "codigo": e.get("codigo") or e.get("Codigo"),
            "descricao": _texto_msg(e),
            "complemento": e.get("complemento") or e.get("Complemento"),
        })
    return erros


def _msg_erros(erros: list[dict[str, str | None]]) -> str:
    """O texto do 1º erro (sem o código — quem monta "[E0xxx] …" é o chamador) e os demais
    inteiros, separados por " | ". Antes da 1.2.0 só o primeiro chegava a quem chamou."""
    def um(e: dict[str, str | None]) -> str:
        return " — ".join(p for p in (e["descricao"], e["complemento"]) if p)

    partes = [um(erros[0]) or "erro na emissão"]
    for e in erros[1:]:
        texto = um(e)
        partes.append(f"[{e['codigo']}] {texto}" if e["codigo"] else texto)
    return " | ".join(p for p in partes if p)


def _falha_http(status: int, contexto: str) -> str:
    """"<contexto> (HTTP 503) — SEFIN fora do ar (…)". O "HTTP NNN" fica no texto de
    propósito: quem consome a mensagem pode casar o status por ele."""
    expl = explicar_http(status)
    return f"{contexto} (HTTP {status})" + (f" — {expl}" if expl else "")


class SefinClient:
    """Cliente HTTP do SEFIN Nacional autenticado por certificado A1 (mTLS).

    `verificar_servidor`: None (padrão) confere o certificado do servidor nos endpoints
    nacionais e não confere nos de município; True/False forçam; uma string é o caminho de um
    arquivo de autoridades (CA bundle) a usar na conferência.
    """

    def __init__(self, *, ambiente: str, cert_pfx_path: str, senha: str,
                 codigo_municipio: str | None = None, timeout: int = 60,
                 verificar_servidor: bool | str | None = None):
        self.base_url = resolver_endpoint(ambiente, codigo_municipio).rstrip("/")
        self.adn_url = ENDPOINTS_ADN[ambiente]
        self.timeout = timeout
        if verificar_servidor is None:
            verificar_servidor = not (codigo_municipio and codigo_municipio in ENDPOINTS_MUNICIPIO)
        self.verificar_servidor: bool | str = verificar_servidor
        self._sessao = requests.Session()
        # mTLS com o .pfx DIRETO (PKCS#12), como o cURL P12 da referência PHP.
        with warnings.catch_warnings():
            # .pfx ICP-Brasil costuma ser BER (não DER) — a leitura funciona; só silencia o aviso.
            warnings.filterwarnings("ignore", message=".*could not be parsed as DER.*")
            self._sessao.mount(
                "https://", Pkcs12Adapter(pkcs12_filename=cert_pfx_path, pkcs12_password=senha)
            )

    def _req(self, metodo: str, caminho: str, **kw: Any) -> requests.Response:
        return self._req_url(metodo, f"{self.base_url}/{caminho}", **kw)

    def _req_url(self, metodo: str, url: str, **kw: Any) -> requests.Response:
        with warnings.catch_warnings():
            if self.verificar_servidor is False:
                # silencia o aviso SÓ aqui — catch_warnings restaura o filtro global do
                # processo do consumidor ao sair.
                warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            return self._sessao.request(
                metodo, url, timeout=self.timeout, verify=self.verificar_servidor, **kw,
            )

    def verificar_dps(self, id_dps: str) -> bool:
        """HEAD /dps/{id} — True se a DPS já foi emitida (200), False se não (404)."""
        r = self._req("HEAD", f"dps/{id_dps}")
        if r.status_code == 200:
            return True
        if r.status_code == 404:
            return False
        raise RuntimeError(_falha_http(r.status_code, "verificarDps falhou"))

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

    def consultar_nfse(self, chave: str) -> str | None:
        """GET /nfse/{chave} → XML da NFS-e; None se a chave não existe (404).

        Qualquer outra resposta levanta `RuntimeError` — "não deu para saber" nunca vira
        "não existe"."""
        r = self._req("GET", f"nfse/{chave}", headers={"Accept": "application/json"})
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise RuntimeError(_falha_http(r.status_code, "consulta da NFS-e falhou"))
        try:
            b64 = r.json().get("nfseXmlGZipB64")
        except ValueError:
            raise RuntimeError("consulta da NFS-e: resposta não-JSON") from None
        if not b64:
            raise RuntimeError("consulta da NFS-e: resposta sem o XML")
        return _descomprimir(b64)

    def emitir(self, xml_dps_assinado: str) -> RespostaSefin:
        """gzip+base64 → POST /nfse (mTLS) → parse da NFS-e. Mapeia E-codes em erro_codigo."""
        logger.info("POST %s/nfse (%d bytes de DPS assinado)", self.base_url,
                    len(xml_dps_assinado))
        r = self._req(
            "POST", "nfse",
            json={"dpsXmlGZipB64": _comprimir(xml_dps_assinado)},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        logger.info("SEFIN respondeu HTTP %d (%d bytes)", r.status_code, len(r.text))
        return self._parsear(r)

    def registrar_evento(self, chave: str, xml_evento_assinado: str) -> RespostaEvento:
        """POST /nfse/{chave}/eventos com o pedido de registro de evento assinado."""
        logger.info("POST %s/nfse/<chave>/eventos (%d bytes)", self.base_url,
                    len(xml_evento_assinado))
        r = self._req(
            "POST", f"nfse/{chave}/eventos",
            json={"pedidoRegistroEventoXmlGZipB64": _comprimir(xml_evento_assinado)},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        logger.info("SEFIN respondeu HTTP %d ao evento", r.status_code)
        bruto = r.text
        try:
            dados: dict[str, Any] = r.json()
        except ValueError:
            return RespostaEvento(ok=False, http_status=r.status_code, raw=bruto,
                                  erro_msg=_falha_http(r.status_code, "resposta não-JSON"))
        erros = _erros(dados)
        if erros:
            return RespostaEvento(ok=False, erro_codigo=erros[0]["codigo"],
                                  erro_msg=_msg_erros(erros), erros=erros,
                                  http_status=r.status_code, raw=bruto)
        b64 = dados.get("eventoXmlGZipB64")
        if not b64:
            return RespostaEvento(ok=False, http_status=r.status_code, raw=bruto,
                                  erro_msg=_falha_http(r.status_code, "resposta sem o evento"))
        return RespostaEvento(ok=True, evento_xml=_descomprimir(b64),
                              http_status=r.status_code, raw=bruto)

    def distribuicao_dfe(self, nsu: int, cnpj: str, lote: bool = True) -> requests.Response:
        """GET {adn}/contribuintes/DFe/{nsu}?cnpjConsulta=… — uma página da caixa postal.

        Devolve a resposta crua: a paginação, o 429 e o 404 ("nenhum documento") são
        tratados em `dfe.sincronizar`."""
        return self._req_url(
            "GET", f"{self.adn_url}/contribuintes/DFe/{int(nsu)}",
            params={"cnpjConsulta": cnpj, "lote": "true" if lote else "false"},
            headers={"Accept": "application/json"},
        )

    def _parsear(self, r: requests.Response) -> RespostaSefin:
        bruto = r.text
        try:
            dados: dict[str, Any] = r.json()
        except ValueError:
            return RespostaSefin(ok=False, http_status=r.status_code, raw=bruto,
                                 erro_msg=_falha_http(r.status_code, "resposta não-JSON"))

        erros = _erros(dados)
        if erros:
            return RespostaSefin(ok=False, erro_codigo=erros[0]["codigo"],
                                 erro_msg=_msg_erros(erros), erros=erros,
                                 http_status=r.status_code, raw=bruto)

        b64 = dados.get("nfseXmlGZipB64")
        if not b64:
            if r.status_code >= 500 or r.status_code in FALHAS_HTTP:
                return RespostaSefin(ok=False, http_status=r.status_code, raw=bruto,
                                     erro_msg=_falha_http(r.status_code, "SEFIN"))
            return RespostaSefin(ok=False, http_status=r.status_code, raw=bruto,
                                 erro_msg="resposta sem XML da NFS-e")

        nfse_xml = _descomprimir(b64)
        alertas = [_texto_msg(a) for a in (dados.get("alertas") or [])]
        return RespostaSefin(
            ok=True,
            nfse_xml=nfse_xml,
            chave_acesso=dados.get("chaveAcesso") or _tag(nfse_xml, "chNFSe"),
            numero_nfse=_tag(nfse_xml, "nNFSe"),
            alertas=[a for a in alertas if a],
            http_status=r.status_code,
            raw=bruto,
        )

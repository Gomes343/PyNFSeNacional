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
import threading
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import requests
import urllib3
from requests_pkcs12 import Pkcs12Adapter

# Logamos status/contexto, NUNCA o payload (XML com dados do tomador) nem a senha do .pfx.
logger = logging.getLogger("pynfsenacional.sefin")

# .pfx ICP-Brasil costuma ser BER (não DER): a leitura funciona e a `cryptography` só avisa.
# O filtro é posto UMA vez, no import, e só para essa mensagem — até a 1.6.0 cada requisição
# abria um `warnings.catch_warnings()`, que salva e restaura a lista GLOBAL de filtros e, com
# duas threads, deixava filtros de uma valendo para o processo inteiro (ou apagava os de
# terceiros). O `InsecureRequestWarning` dos endpoints sem conferência NÃO é silenciado aqui:
# a decisão é de quem usa a lib (`urllib3.disable_warnings`).
warnings.filterwarnings("ignore", message=".*could not be parsed as DER.*")


class PrazoEsgotado(requests.exceptions.Timeout):
    """A requisição passou do prazo TOTAL (`prazo_total_s`) — conexão, envio e resposta
    somados. Como todo timeout depois de o pedido sair, quer dizer "não sei se chegou"."""

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


#: Desfechos de um pedido de evento (`RespostaEvento.desfecho`).
REGISTRADO = "registrado"    # a SEFIN registrou e devolveu o evento
RECUSADO = "recusado"        # a SEFIN respondeu e NÃO registrou (E-code ou HTTP de recusa)
NAO_ENVIADO = "nao_enviado"  # o pedido não saiu (conexão não abriu): nada chegou à SEFIN
AMBIGUO = "ambiguo"          # saiu e a resposta não veio ou não diz: PODE ter sido registrado

#: E-code da SEFIN para "o evento de Cancelamento já está vinculado à NFS-e" (medido em
#: homologação, §16). ☠️ NÃO prova que a nota está cancelada: a SEFIN devolve o mesmo E0840
#: ao e101101 de uma nota que só tem o PEDIDO DE ANÁLISE (e101103) — medido em homologação.
#: Para saber, pergunte `SefinClient.situacao_cancelamento`.
E_EVENTO_JA_VINCULADO = "E0840"

#: Eventos que deixam a nota CANCELADA (tiposEventos v1.01): cancelamento direto, por
#: substituição, deferido por análise fiscal e por ofício.
EVENTOS_QUE_CANCELAM = ("101101", "105102", "105104", "305101")
EVENTO_PEDIDO_ANALISE = "101103"
EVENTO_ANALISE_INDEFERIDA = "105105"

#: Respostas de `SefinClient.situacao_cancelamento`.
CANCELADA = "cancelada"            # há um evento que cancela
EM_ANALISE = "em_analise"          # só o pedido de análise, sem decisão: a nota segue válida
INDEFERIDA = "indeferida"          # a análise negou o cancelamento: a nota segue válida
SEM_CANCELAMENTO = "sem_cancelamento"  # ☠️ NÃO prova nada: a produção não acha, logo depois,
#                                        um cancelamento recém-registrado (medido, 06/11/2026)


@dataclass
class RespostaEvento:
    ok: bool
    evento_xml: str | None = None   # o evento registrado, como a SEFIN devolve
    erro_codigo: str | None = None
    erro_msg: str | None = None
    erros: list[dict[str, str | None]] = field(default_factory=list)
    http_status: int | None = None
    raw: str | None = None
    # REGISTRADO | RECUSADO | NAO_ENVIADO | AMBIGUO. ☠️ AMBIGUO não é "falhou": o pedido saiu
    # e a SEFIN pode tê-lo registrado (ex.: timeout depois do POST, 5xx sem corpo). Confira a
    # nota antes de repetir — repetido, um cancelamento já registrado volta E0840.
    desfecho: str = RECUSADO

    @property
    def ambiguo(self) -> bool:
        """True quando não dá para saber se a SEFIN registrou o evento."""
        return self.desfecho == AMBIGUO

    @property
    def ja_vinculado(self) -> bool:
        """True quando a recusa é o E0840. ☠️ Não quer dizer "cancelada": pode ser só o pedido
        de análise — confira com `conferir_e0840`."""
        return any(e.get("codigo") == E_EVENTO_JA_VINCULADO for e in self.erros)


def conferir_e0840(cliente: SefinClient, chave: str) -> tuple[str | None, str]:
    """O e101101 voltou E0840: o que a nota TEM? Devolve (situação, explicação), com a situação
    de `situacao_cancelamento` ou None quando a consulta falhou (aí NÃO SEI se está cancelada).

    ☠️ O E0840 sozinho não prova cancelamento: em homologação ele voltou para uma nota que só
    tinha o pedido de análise (e101103). Dizer "já estava cancelada" nesse caso marcaria como
    cancelada uma nota que segue válida."""
    try:
        sit = cliente.situacao_cancelamento(chave)
    except Exception as e:  # noqa: BLE001 — rede, status inesperado: não sei
        return None, (f"a SEFIN respondeu E0840 (já há um evento de cancelamento vinculado) e a "
                      f"consulta dos eventos falhou ({e}): NÃO SEI se a nota está cancelada ou em "
                      f"análise — confira no portal")
    return sit, {
        CANCELADA: "a SEFIN respondeu E0840 e a consulta dos eventos confirma: a nota JÁ ESTAVA "
                   "cancelada",
        EM_ANALISE: "a SEFIN respondeu E0840, mas a nota NÃO está cancelada: tem um pedido de "
                    "análise fiscal (e101103) aguardando o município — ela segue válida até o "
                    "deferimento",
        INDEFERIDA: "a SEFIN respondeu E0840, mas a nota NÃO está cancelada: o pedido de análise "
                    "fiscal foi indeferido pelo município — ela segue válida",
        SEM_CANCELAMENTO: "a SEFIN respondeu E0840 (já há um evento de cancelamento vinculado) "
                          "e a consulta dos eventos não achou nenhum: NÃO SEI se a nota está "
                          "cancelada ou em análise — confira no portal",
    }[sit]


_RE_COD_SERVICO = re.compile(r"\d{2}\.\d{2}\.\d{2}\.\d{3}")
_RE_COMPETENCIA = re.compile(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?")


def _codigo_municipio(codigo: str | None) -> str:
    """O código IBGE com 7 dígitos (máscara tolerada), ou `ValueError` — antes de consultar."""
    mun = re.sub(r"\D", "", codigo or "")
    if len(mun) != 7:
        raise ValueError(f"código do município (IBGE) deve ter 7 dígitos; recebido {codigo!r}")
    return mun


def resolver_endpoint(ambiente: str, codigo_municipio: str | None = None) -> str:
    """Resolve a base URL do SEFIN por ambiente, com override por município (IBGE)."""
    if ambiente not in ENDPOINTS:
        raise ValueError(f"ambiente inválido: {ambiente!r} (use 'homologacao' ou 'producao')")
    if codigo_municipio and codigo_municipio in ENDPOINTS_MUNICIPIO:
        return ENDPOINTS_MUNICIPIO[codigo_municipio][ambiente]
    return ENDPOINTS[ambiente]


def _descomprimir_bytes(b64: str) -> bytes:
    """base64 → gzip → os bytes do XML, sem decodificar."""
    return gzip.decompress(base64.b64decode(b64))


def _descomprimir(b64: str) -> str:
    """base64 → gzip → XML (campo *XmlGZipB64 do SEFIN), em UTF-8 estrito."""
    return _descomprimir_bytes(b64).decode("utf-8")


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


def _com_prazo(prazo: float, fn: Callable[[], requests.Response]) -> requests.Response:
    """Roda `fn` (uma requisição) numa thread e espera no máximo `prazo` segundos de relógio.

    Estourado, levanta `PrazoEsgotado` e quem chamou segue; a thread abandonada termina
    sozinha, no `timeout` por operação (que `_timeout_ate` já cortou para caber no prazo)."""
    saida: dict[str, Any] = {}

    def alvo() -> None:
        try:
            saida["r"] = fn()
        except BaseException as e:  # noqa: BLE001 — devolvida a quem chamou, abaixo
            saida["e"] = e

    t = threading.Thread(target=alvo, name="pynfsenacional-http", daemon=True)
    t.start()
    t.join(prazo)
    if t.is_alive():
        raise PrazoEsgotado(f"sem resposta completa em {prazo:g} s (prazo total da requisição)")
    if "e" in saida:
        raise saida["e"]
    resposta: requests.Response = saida["r"]
    return resposta


def _antes_do_envio(exc: BaseException) -> bool:
    """A exceção de rede prova que o pedido NÃO saiu? Só quando a conexão nem abriu: tempo
    esgotado ao conectar, recusa da conexão, nome que não resolve, URL inválida. Todo o
    resto (tempo de leitura, conexão caída no meio, erro de TLS depois do aperto de mão) é
    "pode ter chegado" — na dúvida, conta como enviado."""
    if isinstance(exc, PrazoEsgotado):
        return False
    if isinstance(exc, (requests.exceptions.ConnectTimeout, requests.exceptions.InvalidURL,
                        requests.exceptions.MissingSchema, requests.exceptions.InvalidSchema)):
        return True
    if isinstance(exc, requests.exceptions.ConnectionError) and not isinstance(
            exc, requests.exceptions.SSLError):
        motivo = exc.args[0] if exc.args else None
        motivo = getattr(motivo, "reason", motivo)        # MaxRetryError → a causa
        return isinstance(motivo, (urllib3.exceptions.NewConnectionError,
                                   urllib3.exceptions.ConnectTimeoutError))
    return False


class SefinClient:
    """Cliente HTTP do SEFIN Nacional autenticado por certificado A1 (mTLS).

    O certificado vem do arquivo (`cert_pfx_path`) ou dos bytes do PKCS#12 (`pkcs12_data`,
    ex. `Certificado.pkcs12_bytes()` — o caminho do .pfx de cifra legada, §9).

    `verificar_servidor`: None (padrão) confere o certificado do servidor nos endpoints
    nacionais (SEFIN e ADN) e não confere SÓ no endpoint próprio do município; True/False
    forçam (todos os endpoints); uma string é o caminho de um arquivo de autoridades (CA
    bundle) a usar na conferência. O ADN é sempre nacional: até a 1.6.0 um prestador de
    município com endpoint próprio falava também com o ADN sem conferir o servidor.

    `timeout`: segundos por operação de rede (conectar; cada leitura), ou o par
    `(conectar, ler)` do `requests`. `prazo_total_s`: teto de RELÓGIO para cada requisição
    inteira (None = sem teto); estourado, levanta `PrazoEsgotado`. Sem ele, uma resposta
    que goteja segura a chamada indefinidamente, porque o `timeout` vale entre bytes.
    """

    def __init__(self, *, ambiente: str, cert_pfx_path: str | None = None,
                 senha: str, codigo_municipio: str | None = None,
                 timeout: float | tuple[float, float] = 60,
                 verificar_servidor: bool | str | None = None,
                 pkcs12_data: bytes | None = None, prazo_total_s: float | None = None):
        if (cert_pfx_path is None) == (pkcs12_data is None):
            raise ValueError("informe cert_pfx_path OU pkcs12_data (um dos dois)")
        self.base_url = resolver_endpoint(ambiente, codigo_municipio).rstrip("/")
        self.adn_url = ENDPOINTS_ADN[ambiente]
        self.timeout = timeout
        self.prazo_total_s = prazo_total_s
        municipio = bool(codigo_municipio and codigo_municipio in ENDPOINTS_MUNICIPIO)
        if verificar_servidor is None:
            self.verificar_servidor: bool | str = not municipio
            self.verificar_adn: bool | str = True
        else:
            self.verificar_servidor = self.verificar_adn = verificar_servidor
        if self.verificar_servidor is False:
            logger.warning("SefinClient: o certificado do servidor NÃO é conferido em %s",
                           self.base_url)
        #: A `mensagem` do ADN na última consulta de parametrização (ex. "Convênio para o
        #: município não encontrado."), para quem mostra a resposta a uma pessoa.
        self.ultima_mensagem_adn: str | None = None
        self._sessao = requests.Session()
        # mTLS com o .pfx DIRETO (PKCS#12), como o cURL P12 da referência PHP.
        if pkcs12_data is not None:
            adaptador = Pkcs12Adapter(pkcs12_data=pkcs12_data, pkcs12_password=senha)
        else:
            adaptador = Pkcs12Adapter(pkcs12_filename=cert_pfx_path, pkcs12_password=senha)
        self._sessao.mount("https://", adaptador)

    def _req(self, metodo: str, caminho: str, **kw: Any) -> requests.Response:
        return self._req_url(metodo, f"{self.base_url}/{caminho}", **kw)

    def _verify_de(self, url: str) -> bool | str:
        """A conferência do servidor para ESTA url: o ADN tem a sua; o resto, a do SEFIN
        ou do município."""
        return self.verificar_adn if url.startswith(self.adn_url) else self.verificar_servidor

    def _timeout_ate(self, prazo: float | None) -> float | tuple[float, float]:
        if prazo is None:
            return self.timeout
        if isinstance(self.timeout, tuple):
            return (min(self.timeout[0], prazo), min(self.timeout[1], prazo))
        return min(self.timeout, prazo)

    def _req_url(self, metodo: str, url: str, *, prazo_s: float | None = None,
                 **kw: Any) -> requests.Response:
        """Uma requisição. `prazo_s` (ou o `prazo_total_s` do cliente) é o teto de relógio da
        requisição inteira; sem prazo, valem só os timeouts por operação."""
        prazo = prazo_s if prazo_s is not None else self.prazo_total_s

        def chamar() -> requests.Response:
            return self._sessao.request(metodo, url, timeout=self._timeout_ate(prazo),
                                        verify=self._verify_de(url), **kw)

        if prazo is None:
            return chamar()
        return _com_prazo(prazo, chamar)

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

    def evento_registrado(self, chave: str, tipo_evento: str, sequencial: int = 1) -> bool:
        """GET /nfse/{chave}/eventos/{tipo}/{seq} → True se o evento está registrado na nota.

        404 com corpo JSON = o evento não existe (False). Qualquer outra resposta — inclusive
        404 sem JSON, que é rota errada, não "não existe" — levanta `RuntimeError`."""
        r = self._req("GET", f"nfse/{chave}/eventos/{tipo_evento}/{int(sequencial)}",
                      headers={"Accept": "application/json"})
        try:
            dados = r.json()
        except ValueError:
            dados = None
        if r.status_code == 404 and isinstance(dados, dict):
            return False
        if r.status_code != 200:
            raise RuntimeError(_falha_http(r.status_code, f"consulta do evento {tipo_evento}"))
        if not isinstance(dados, dict) or not isinstance(dados.get("eventos"), list):
            raise RuntimeError(f"consulta do evento {tipo_evento}: resposta sem a lista de eventos")
        return len(dados["eventos"]) > 0

    def situacao_cancelamento(self, chave: str) -> str:
        """A nota está cancelada? Pergunta à SEFIN pelos eventos, em vez de deduzir de um
        E-code: `CANCELADA` | `EM_ANALISE` | `INDEFERIDA` | `SEM_CANCELAMENTO`.

        Levanta `RuntimeError` quando não dá para saber (rede, status inesperado)."""
        for tipo in EVENTOS_QUE_CANCELAM:
            if self.evento_registrado(chave, tipo):
                return CANCELADA
        if self.evento_registrado(chave, EVENTO_PEDIDO_ANALISE):
            if self.evento_registrado(chave, EVENTO_ANALISE_INDEFERIDA):
                return INDEFERIDA
            return EM_ANALISE
        return SEM_CANCELAMENTO

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

    def registrar_evento(self, chave: str, xml_evento_assinado: str, *,
                         prazo_s: float | None = None) -> RespostaEvento:
        """POST /nfse/{chave}/eventos com o pedido de registro de evento assinado.

        Um POST só, sem retentativa (repetir um evento é decisão de quem chama). Não levanta
        por falha de rede: o `desfecho` diz o que aconteceu —
          • REGISTRADO  — `ok=True`, `evento_xml` com o evento que a SEFIN devolveu;
          • RECUSADO    — a SEFIN respondeu e não registrou (`erro_codigo`/`erros`; o E0840,
                          "já vinculado", está em `ja_vinculado`);
          • NAO_ENVIADO — a conexão nem abriu: nada chegou à SEFIN;
          • AMBIGUO     — o pedido saiu e a resposta não veio (tempo esgotado, conexão caída,
                          `prazo_s`/`prazo_total_s` estourado) ou não diz nada (5xx sem corpo,
                          2xx sem o evento). PODE ter sido registrado: confira a nota antes
                          de repetir.
        """
        logger.info("POST %s/nfse/<chave>/eventos (%d bytes)", self.base_url,
                    len(xml_evento_assinado))
        try:
            r = self._req(
                "POST", f"nfse/{chave}/eventos",
                json={"pedidoRegistroEventoXmlGZipB64": _comprimir(xml_evento_assinado)},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                **({"prazo_s": prazo_s} if prazo_s is not None else {}),
            )
        except requests.exceptions.RequestException as e:
            if _antes_do_envio(e):
                logger.warning("evento NÃO enviado (%s)", type(e).__name__)
                return RespostaEvento(ok=False, desfecho=NAO_ENVIADO,
                                      erro_msg=f"o pedido não saiu ({type(e).__name__}: {e}) "
                                               "— nada chegou à SEFIN")
            logger.warning("evento AMBÍGUO: o pedido saiu e a resposta não veio (%s)",
                           type(e).__name__)
            return RespostaEvento(ok=False, desfecho=AMBIGUO,
                                  erro_msg=f"o pedido saiu e a resposta não veio "
                                           f"({type(e).__name__}: {e}) — a SEFIN pode ter "
                                           "registrado o evento; confira a nota antes de "
                                           "repetir")
        logger.info("SEFIN respondeu HTTP %d ao evento", r.status_code)
        bruto = r.text
        try:
            dados: dict[str, Any] = r.json()
            if not isinstance(dados, dict):
                raise ValueError("JSON que não é objeto")
        except ValueError:
            # Sem corpo legível: 5xx/408 pode ter sido processado (o gateway desistiu antes
            # da resposta); 4xx é a borda recusando (certificado, taxa, rota).
            ambiguo = r.status_code >= 500 or r.status_code == 408
            return RespostaEvento(ok=False, http_status=r.status_code, raw=bruto,
                                  desfecho=AMBIGUO if ambiguo else RECUSADO,
                                  erro_msg=_falha_http(r.status_code, "resposta não-JSON")
                                  + (" — a SEFIN pode ter registrado o evento; confira a "
                                     "nota antes de repetir" if ambiguo else ""))
        erros = _erros(dados)
        if erros:
            return RespostaEvento(ok=False, erro_codigo=erros[0]["codigo"],
                                  erro_msg=_msg_erros(erros), erros=erros,
                                  http_status=r.status_code, raw=bruto, desfecho=RECUSADO)
        b64 = dados.get("eventoXmlGZipB64")
        if not b64:
            # Sem erro e sem o evento: 2xx/5xx não dizem que não registrou; 4xx sim.
            ambiguo = not 400 <= r.status_code < 500 or r.status_code == 408
            return RespostaEvento(ok=False, http_status=r.status_code, raw=bruto,
                                  desfecho=AMBIGUO if ambiguo else RECUSADO,
                                  erro_msg=_falha_http(r.status_code, "resposta sem o evento")
                                  + (" — a SEFIN pode ter registrado o evento; confira a "
                                     "nota antes de repetir" if ambiguo else ""))
        return RespostaEvento(ok=True, evento_xml=_descomprimir(b64),
                              http_status=r.status_code, raw=bruto, desfecho=REGISTRADO)

    def distribuicao_dfe(self, nsu: int, cnpj: str, lote: bool = True, *,
                         prazo_s: float | None = None) -> requests.Response:
        """GET {adn}/contribuintes/DFe/{nsu}?cnpjConsulta=… — uma página da caixa postal.

        Devolve a resposta crua: a paginação, o 429 e o 404 ("nenhum documento") são
        tratados em `dfe.sincronizar`. `prazo_s`: teto de relógio desta requisição."""
        return self._req_url(
            "GET", f"{self.adn_url}/contribuintes/DFe/{int(nsu)}",
            params={"cnpjConsulta": cnpj, "lote": "true" if lote else "false"},
            headers={"Accept": "application/json"},
            **({"prazo_s": prazo_s} if prazo_s is not None else {}),
        )

    # ── parametrização do município (ADN, só leitura) ─────────────────────────
    def _get_parametrizacao(self, caminho: str, contexto: str,
                            chave: str) -> dict[str, Any] | None:
        """GET {adn}/parametrizacao/… → o JSON; None no 404 DO ADN ("não há o parâmetro").

        O 404 só vira None quando o corpo é a resposta do ADN — um objeto JSON com a `chave`
        esperada (`parametrosConvenio`/`aliquotas`) ou a `mensagem` dele. Um 404 sem esse corpo
        (rota que não existe, página de erro de um intermediário) levanta, como qualquer outro
        status: "não deu para saber" nunca vira "não existe". A `mensagem` do ADN fica em
        `ultima_mensagem_adn`."""
        self.ultima_mensagem_adn = None
        r = self._req_url("GET", f"{self.adn_url}/parametrizacao/{caminho}",
                          headers={"Accept": "application/json"})
        if r.status_code not in (200, 404):
            raise RuntimeError(_falha_http(r.status_code, contexto))
        try:
            dados = r.json()
        except ValueError:
            raise RuntimeError(f"{contexto}: resposta não-JSON (HTTP {r.status_code})") from None
        if not isinstance(dados, dict):
            raise RuntimeError(f"{contexto}: resposta inesperada (HTTP {r.status_code})")
        msg = dados.get("mensagem") or dados.get("Mensagem")
        self.ultima_mensagem_adn = str(msg) if msg else None
        if r.status_code == 404:
            if chave in dados or msg:
                return None
            raise RuntimeError(f"{contexto} (HTTP 404 sem a resposta do ADN)")
        if chave not in dados:
            raise RuntimeError(f"{contexto}: resposta sem '{chave}'")
        return dados

    def parametros_convenio(self, codigo_municipio: str) -> dict[str, Any] | None:
        """Os parâmetros do convênio do município (IBGE, 7 díg) com o ambiente nacional —
        `aderenteAmbienteNacional`, `aderenteEmissorNacional`, … (1 = sim). None se o
        município não tem convênio (o 404 do ADN). `ValueError` se o código não tiver 7
        dígitos — sem consultar."""
        mun = _codigo_municipio(codigo_municipio)
        dados = self._get_parametrizacao(f"{mun}/convenio",
                                         "consulta do convênio do município falhou",
                                         "parametrosConvenio")
        if dados is None:
            return None
        par = dados.get("parametrosConvenio")
        if not isinstance(par, dict):
            raise RuntimeError("consulta do convênio do município: 'parametrosConvenio' vazio "
                               "numa resposta de sucesso")
        return par

    def aliquotas(self, codigo_municipio: str, codigo_servico: str,
                  competencia: str | None = None) -> list[dict[str, Any]]:
        """As alíquotas de ISS que o município parametrizou para o serviço
        (`codigo_servico` = cTribNac + cTribMun no formato `00.00.00.000`) na `competencia`
        (AAAA-MM-DD; sem ela, o histórico inteiro). Cada item: `Incidencia`, `Aliq`, `DtIni`,
        `DtFim`. Lista vazia = o município não administra esse código (é o que antecede o
        E0312 na emissão). `ValueError`, sem consultar, para município sem 7 dígitos, código
        fora do formato ou competência que não seja AAAA-MM-DD."""
        mun = _codigo_municipio(codigo_municipio)
        cod = (codigo_servico or "").strip()
        if not _RE_COD_SERVICO.fullmatch(cod):
            raise ValueError(f"código do serviço deve ser 00.00.00.000 (cTribNac + cTribMun); "
                             f"recebido {codigo_servico!r}")
        serv = quote(cod, safe="")
        if competencia:
            comp = competencia.strip()
            if not _RE_COMPETENCIA.fullmatch(comp):
                raise ValueError(f"competência deve ser AAAA-MM-DD; recebido {competencia!r}")
            dh = comp if "T" in comp else f"{comp}T12:00:00"
            caminho = f"{mun}/{serv}/{quote(dh, safe='')}/aliquota"
        else:
            caminho = f"{mun}/{serv}/historicoaliquotas"
        dados = self._get_parametrizacao(caminho, "consulta de alíquota falhou", "aliquotas")
        lista = ((dados or {}).get("aliquotas") or {}).get(cod) or []
        return [a for a in lista if isinstance(a, dict)]

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

"""Assinatura digital XMLDSIG da DPS. Lib: `erpbrasil.assinatura` (signxml).

★ Era o ponto que parecia o "nó" — resolvido por biblioteca madura (em produção no
ecossistema Odoo Brasil). Assinatura *enveloped* sobre o nó `infDPS`, com `Reference`
apontando para o `Id`. Validado contra a referência PHP: o `DigestValue` produzido aqui
é **byte-a-byte idêntico** ao do gabarito (RSA-SHA1 + transforms enveloped/c14n) — ver
tests/golden. A `<Signature>` entra como último filho do `<DPS>`, depois do `infDPS`.
"""

from __future__ import annotations

import base64

from lxml import etree

NS = "http://www.sped.fazenda.gov.br/nfse"


def assinar_dps(xml_dps: str, *, cert_pfx_path: str | None = None, senha: str,
                pkcs12_data: bytes | None = None) -> str:
    """Recebe o XML da DPS (não assinado) e devolve o XML assinado (XMLDSIG enveloped).

    Delegado a `erpbrasil.assinatura`: assina apontando o `Reference` para o `Id` do
    `infDPS`. RSA-SHA1 (algoritmo do padrão NFe/NFSe). O certificado vem do arquivo
    (`cert_pfx_path`) ou dos bytes do PKCS#12 (`pkcs12_data`, ex. `Certificado.pkcs12_bytes()`).
    """
    return assinar_xml(xml_dps, "infDPS", cert_pfx_path=cert_pfx_path, senha=senha,
                       pkcs12_data=pkcs12_data)


def assinar_xml(xml: str, no: str, *, cert_pfx_path: str | None = None, senha: str,
                pkcs12_data: bytes | None = None) -> str:
    """Assina o filho `no` da raiz (pelo `Id` dele) e devolve o XML com o prolog UTF-8.

    O mesmo perfil da DPS serve ao pedido de evento (`infPedReg`): a `<Signature>` entra
    como último filho da raiz, depois do nó assinado.

    Informe UM dos dois: `cert_pfx_path` (o .pfx em disco) ou `pkcs12_data` (os bytes do
    PKCS#12). Os bytes servem ao .pfx de cifra legada que só abriu pelo fallback do
    `Certificado` (§9): o arquivo original, relido aqui, daria "senha inválida".
    """
    if (cert_pfx_path is None) == (pkcs12_data is None):
        raise ValueError("informe cert_pfx_path OU pkcs12_data (um dos dois)")
    from erpbrasil.assinatura.assinatura import Assinatura
    from erpbrasil.assinatura.certificado import Certificado

    raiz = etree.fromstring(xml.encode("utf-8"))
    inf = raiz.find(f"{{{NS}}}{no}")
    if inf is None:
        raise ValueError(f"XML sem nó {no} — nada para assinar")
    reference = inf.get("Id")
    if not reference:
        raise ValueError(f"{no} sem atributo Id — assinatura precisa do Reference")

    # O erpbrasil aceita o caminho do arquivo ou o PKCS#12 em base64 (bytes).
    origem = cert_pfx_path if pkcs12_data is None else base64.b64encode(pkcs12_data)
    cert = Certificado(origem, senha)
    assinado = Assinatura(cert).assina_xml2(raiz, reference)

    # Reserializa com o prolog `<?xml version='1.0' encoding='UTF-8'?>` — sem ele o SEFIN
    # rejeita com E1229 ("Xml não está utilizando codificação UTF-8"). O prolog fica FORA
    # do infDPS/Signature, então não altera o DigestValue nem a assinatura já calculados.
    if isinstance(assinado, str):
        elem = etree.fromstring(assinado.encode("utf-8"))
    elif isinstance(assinado, bytes):
        elem = etree.fromstring(assinado)
    else:
        elem = assinado
    return str(etree.tostring(elem, encoding="UTF-8", xml_declaration=True).decode("utf-8"))

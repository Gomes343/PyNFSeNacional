"""Assinatura digital XMLDSIG da DPS. Lib: `erpbrasil.assinatura` (signxml).

★ Era o ponto que parecia o "nó" — resolvido por biblioteca madura (em produção no
ecossistema Odoo Brasil). Assinatura *enveloped* sobre o nó `infDPS`, com `Reference`
apontando para o `Id`. Validado contra a referência PHP: o `DigestValue` produzido aqui
é **byte-a-byte idêntico** ao do gabarito (RSA-SHA1 + transforms enveloped/c14n) — ver
tests/golden. A `<Signature>` entra como último filho do `<DPS>`, depois do `infDPS`.
"""

from __future__ import annotations

from lxml import etree

NS = "http://www.sped.fazenda.gov.br/nfse"


def assinar_dps(xml_dps: str, *, cert_pfx_path: str, senha: str) -> str:
    """Recebe o XML da DPS (não assinado) e devolve o XML assinado (XMLDSIG enveloped).

    Delegado a `erpbrasil.assinatura`: assina apontando o `Reference` para o `Id` do
    `infDPS`. RSA-SHA1 (algoritmo do padrão NFe/NFSe).
    """
    from erpbrasil.assinatura.assinatura import Assinatura
    from erpbrasil.assinatura.certificado import Certificado

    raiz = etree.fromstring(xml_dps.encode("utf-8"))
    inf = raiz.find(f"{{{NS}}}infDPS")
    if inf is None:
        raise ValueError("DPS sem nó infDPS — nada para assinar")
    reference = inf.get("Id")
    if not reference:
        raise ValueError("infDPS sem atributo Id — assinatura precisa do Reference")

    cert = Certificado(cert_pfx_path, senha)
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

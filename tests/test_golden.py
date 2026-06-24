"""Golden harness (Fase 4) — o desrisco central da canonicalização XMLDSIG.

Prova, SEM tocar o SEFIN, que a DPS construída em Python é **byte-a-byte idêntica**
(na forma canônica C14N) à da referência PHP que já emite em produção. O gabarito
(`gabarito_dps_assinado.xml`) foi gerado por `regenerar_gabarito.sh` com um certificado
de teste descartável; o golden extrai dele as entradas voláteis (dhEmi/dCompet/verAplic)
para a comparação ser determinística. Roda no CI sem PHP e sem segredo.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from conftest import gerar_pfx_teste
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree

from pynfsenacional import dps
from pynfsenacional.assinatura import assinar_dps
from pynfsenacional.config import ClienteConfig

NSN = "http://www.sped.fazenda.gov.br/nfse"
NSD = "http://www.w3.org/2000/09/xmldsig#"
GOLDEN = Path(__file__).parent / "golden"


def _digest_exclusivo(inf: etree._Element) -> str:
    c14n = etree.tostring(inf, method="c14n", exclusive=True)
    return base64.b64encode(hashlib.sha1(c14n).digest()).decode()


@pytest.fixture
def gabarito() -> dict:
    t = etree.parse(str(GOLDEN / "gabarito_dps_assinado.xml"))
    inf = t.find(f".//{{{NSN}}}infDPS")
    cfg = json.loads((GOLDEN / "gabarito_config.json").read_text())
    return {
        "inf": inf,
        "c14n": etree.tostring(inf, method="c14n", exclusive=True),
        "digest_declarado": t.find(f".//{{{NSD}}}DigestValue").text,
        "dh_emi": inf.find(f"{{{NSN}}}dhEmi").text,
        "d_comp": inf.find(f"{{{NSN}}}dCompet").text,
        "ver_aplic": inf.find(f"{{{NSN}}}verAplic").text,
        "cfg": cfg,
    }


def test_gabarito_autoconsistente(gabarito):
    """O DigestValue declarado no gabarito = SHA1 do C14N exclusivo do seu infDPS.
    (Valida nosso entendimento da canonicalização do assinador de referência.)"""
    assert _digest_exclusivo(gabarito["inf"]) == gabarito["digest_declarado"]


def test_montar_dps_bate_gabarito_byte_a_byte(gabarito):
    """montar_dps, com as MESMAS entradas, produz um infDPS canonicamente idêntico
    ao da referência PHP — byte-a-byte — e portanto o mesmo DigestValue."""
    cfg = ClienteConfig.from_dict(gabarito["cfg"])
    nota = gabarito["cfg"]["dados_nota"]
    xml = dps.montar_dps(
        cfg, numero=nota["numero"], serie=nota["serie"], valor=nota["valor"],
        descricao=nota["descricao"],
        tomador={"cpf_cnpj": nota["tomador"]["cpf_cnpj"], "nome": nota["tomador"]["xNome"]},
        ambiente="homologacao",
        dh_emi=gabarito["dh_emi"], d_comp=gabarito["d_comp"], ver_aplic=gabarito["ver_aplic"],
    )
    inf = etree.fromstring(xml.encode()).find(f"{{{NSN}}}infDPS")
    c14n = etree.tostring(inf, method="c14n", exclusive=True)
    assert c14n == gabarito["c14n"]                                  # byte-a-byte
    assert _digest_exclusivo(inf) == gabarito["digest_declarado"]    # mesmo DigestValue


def _verifica_assinatura(signed_xml: str) -> bool:
    t = etree.fromstring(signed_xml.encode())
    si = t.find(f".//{{{NSD}}}SignedInfo")
    sigval = base64.b64decode(t.find(f".//{{{NSD}}}SignatureValue").text)
    cert = x509.load_der_x509_certificate(
        base64.b64decode(t.find(f".//{{{NSD}}}X509Certificate").text)
    )
    for exclusive in (True, False):
        c14n = etree.tostring(si, method="c14n", exclusive=exclusive)
        try:
            cert.public_key().verify(sigval, c14n, padding.PKCS1v15(), hashes.SHA1())
            return True
        except Exception:
            continue
    return False


def test_assinatura_estrutura_digest_e_verifica(gabarito, tmp_path):
    """assinar_dps produz XMLDSIG com o perfil certo (RSA-SHA1, transforms, Reference=#Id),
    a <Signature> após o infDPS, o MESMO DigestValue do gabarito, e a assinatura verifica."""
    pfx = tmp_path / "t.pfx"
    pfx.write_bytes(gerar_pfx_teste("0000"))
    cfg = ClienteConfig.from_dict(gabarito["cfg"])
    nota = gabarito["cfg"]["dados_nota"]
    xml = dps.montar_dps(
        cfg, numero=nota["numero"], serie=nota["serie"], valor=nota["valor"],
        descricao=nota["descricao"],
        tomador={"cpf_cnpj": nota["tomador"]["cpf_cnpj"], "nome": nota["tomador"]["xNome"]},
        ambiente="homologacao",
        dh_emi=gabarito["dh_emi"], d_comp=gabarito["d_comp"], ver_aplic=gabarito["ver_aplic"],
    )
    assinado = assinar_dps(xml, cert_pfx_path=str(pfx), senha="0000")

    # prolog UTF-8 obrigatório — sem ele o SEFIN rejeita com E1229 (regressão real, homologação)
    assert assinado.startswith("<?xml")
    assert "UTF-8" in assinado[:60]

    t = etree.fromstring(assinado.encode())
    assert etree.QName(t[-1]).localname == "Signature"          # após o infDPS
    assert t.find(f".//{{{NSD}}}SignatureMethod").get("Algorithm").endswith("rsa-sha1")
    assert t.find(f".//{{{NSD}}}DigestMethod").get("Algorithm").endswith("#sha1")
    transforms = [x.get("Algorithm") for x in t.findall(f".//{{{NSD}}}Transform")]
    assert any("enveloped-signature" in a for a in transforms)
    assert t.find(f".//{{{NSD}}}Reference").get("URI") == f"#{nota_id(gabarito)}"
    # DigestValue key-independente → igual ao gabarito
    assert t.find(f".//{{{NSD}}}DigestValue").text == gabarito["digest_declarado"]
    assert _verifica_assinatura(assinado)                       # assinatura válida


def nota_id(gabarito) -> str:
    return gabarito["inf"].get("Id")

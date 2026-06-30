"""Fase 4: construção da DPS (montar_dps) e do Id (id_dps) — unidade.

Aqui testamos a LÓGICA FISCAL da montagem (ordem, omissões dos E-codes, formatação).
O byte-diff canônico contra a referência PHP fica em test_golden.py.
"""

from __future__ import annotations

from conftest import CONFIG_VALIDA
from lxml import etree

from pynfsenacional import dps
from pynfsenacional.config import ClienteConfig

NS = "http://www.sped.fazenda.gov.br/nfse"


def _inf(xml: str) -> etree._Element:
    inf = etree.fromstring(xml.encode()).find(f"{{{NS}}}infDPS")
    assert inf is not None
    return inf


def _txt(inf, caminho: str):
    el = inf.find("/".join(f"{{{NS}}}{p}" for p in caminho.split("/")))
    return el.text if el is not None else None


def test_id_dps_formato():
    cfg = ClienteConfig.from_dict(CONFIG_VALIDA)
    idd = dps.id_dps(cfg, numero="1", serie="1")
    assert idd == "DPS330455721122233300018100001000000000000001"
    assert len(idd) == 45
    assert idd.startswith("DPS3304557")        # IBGE do prestador
    assert idd[10] == "2"                        # tipo inscrição = CNPJ


def test_ver_aplic_ate_20_chars():
    assert len(dps.VER_APLIC) <= 20             # TSVerAplic / E1235


def _montar(cfg, **kw):
    base = dict(numero="1", valor=150.0, descricao="Servico de teste",
                tomador={"cpf_cnpj": "11144477735", "nome": "FULANO DE TAL"},
                ambiente="homologacao", serie="1")
    base.update(kw)
    return dps.montar_dps(cfg, **base)


def test_estrutura_e_ordem():
    inf = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA)))
    ordem = [etree.QName(c).localname for c in inf]
    assert ordem == ["tpAmb", "dhEmi", "verAplic", "serie", "nDPS", "dCompet",
                     "tpEmit", "cLocEmi", "prest", "toma", "serv", "valores"]
    assert _txt(inf, "tpAmb") == "2"             # homologação
    assert _txt(inf, "tpEmit") == "1"            # prestador é o emitente


def test_omite_nome_e_endereco_do_prestador():
    # E0128/E0121: prest = só CNPJ + regTrib (sem xNome, sem end)
    inf = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA)))
    prest = inf.find(f"{{{NS}}}prest")
    filhos = [etree.QName(c).localname for c in prest]
    assert filhos == ["CNPJ", "regTrib"]


def test_inscricao_municipal_vem_antes_do_regtrib():
    # Regressão: a IM (TSInscricaoMunicipal) é uma SEQUÊNCIA no XSD AnexoI e vem ANTES do
    # regTrib. Emiti-la depois gera E1235 (falha de schema) para todo prestador com IM. O
    # gabarito (CONFIG_VALIDA) não tem IM, então o byte-diff não pegava — pegou o diff contra
    # o motor PHP de produção (clientes com inscrição municipal).
    cfg = ClienteConfig.from_dict({**CONFIG_VALIDA,
                                   "prestador": {**CONFIG_VALIDA["prestador"],
                                                 "inscricao_municipal": "02200392"}})
    prest = _inf(_montar(cfg)).find(f"{{{NS}}}prest")
    assert [etree.QName(c).localname for c in prest] == ["CNPJ", "IM", "regTrib"]
    assert prest.find(f"{{{NS}}}IM").text == "02200392"


def test_tomador_identificado_tem_cpf_e_nome():
    inf = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA)))
    assert _txt(inf, "toma/CPF") == "11144477735"
    assert _txt(inf, "toma/xNome") == "FULANO DE TAL"


def test_sem_tomador_omite_bloco():
    inf = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA), tomador=None))
    assert inf.find(f"{{{NS}}}toma") is None


def test_tomador_endereco_fone_email_ordem_do_xsd():
    # Campos opcionais do tomador (end/fone/email) na ORDEM do XSD (TSDestinaDps):
    # CPF|CNPJ → IM → xNome → end → fone → email. Fora de ordem = E1235.
    tom = {
        "cpf_cnpj": "45192564000101", "nome": "PREFEITURA MUNICIPAL DE SILVEIRAS",
        "im": "12345",
        "endereco": {"cep": "12690-000", "logradouro": "ANTONIO PEREIRA AZEVEDO",
                     "numero": "52", "bairro": "CENTRO", "cMun": "3552007"},
        "fone": "(12) 3106-1150", "email": "contato@silveiras.sp.gov.br",
    }
    toma = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA), tomador=tom)).find(f"{{{NS}}}toma")
    assert [etree.QName(c).localname for c in toma] == \
        ["CNPJ", "IM", "xNome", "end", "fone", "email"]
    assert toma.find(f"{{{NS}}}fone").text == "1231061150"        # só dígitos
    assert toma.find(f"{{{NS}}}email").text == "contato@silveiras.sp.gov.br"
    # <end> nacional, ordem interna: endNac(cMun, CEP) → xLgr → nro → xBairro (sem xCpl aqui)
    end = toma.find(f"{{{NS}}}end")
    assert [etree.QName(c).localname for c in end] == ["endNac", "xLgr", "nro", "xBairro"]
    endnac = end.find(f"{{{NS}}}endNac")
    assert [etree.QName(c).localname for c in endnac] == ["cMun", "CEP"]
    assert endnac.find(f"{{{NS}}}cMun").text == "3552007"
    assert endnac.find(f"{{{NS}}}CEP").text == "12690000"         # CEP sem traço, 8 díg
    assert end.find(f"{{{NS}}}xLgr").text == "ANTONIO PEREIRA AZEVEDO"
    assert end.find(f"{{{NS}}}nro").text == "52"
    assert end.find(f"{{{NS}}}xBairro").text == "CENTRO"


def test_tomador_endereco_com_complemento():
    tom = {"cpf_cnpj": "45192564000101", "nome": "X",
           "endereco": {"cep": "12690000", "logradouro": "RUA A", "numero": "10",
                        "complemento": "Sala 2", "bairro": "CENTRO", "cMun": "3552007"}}
    end = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA),
                       tomador=tom)).find(f"{{{NS}}}toma/{{{NS}}}end")
    assert [etree.QName(c).localname for c in end] == ["endNac", "xLgr", "nro", "xCpl", "xBairro"]
    assert end.find(f"{{{NS}}}xCpl").text == "Sala 2"


def test_tomador_endereco_incompleto_e_omitido_atomico():
    # Bloco parcial (sem bairro) = E1235 → omite o endereço INTEIRO (tudo-ou-nada), mas a
    # nota continua válida (CNPJ + xNome). Espelha o gt_montar_endereco do PHP.
    tom = {"cpf_cnpj": "45192564000101", "nome": "X",
           "endereco": {"cep": "12690000", "logradouro": "RUA A", "numero": "10",
                        "cMun": "3552007"}}  # falta xBairro
    toma = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA),
                        tomador=tom)).find(f"{{{NS}}}toma")
    assert toma.find(f"{{{NS}}}end") is None
    assert [etree.QName(c).localname for c in toma] == ["CNPJ", "xNome"]


def test_tomador_sem_extras_xml_inalterado():
    # Sem end/fone/email/IM o <toma> é idêntico ao de antes (só doc + xNome) — garante que a
    # extensão é puramente ADITIVA (o golden, cujo tomador não tem endereço, segue bate-byte).
    toma = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA))).find(f"{{{NS}}}toma")
    assert [etree.QName(c).localname for c in toma] == ["CPF", "xNome"]


def test_par_ctribnac_ctribmun():
    inf = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA)))
    assert _txt(inf, "serv/cServ/cTribNac") == "041601"
    assert _txt(inf, "serv/cServ/cTribMun") == "001"


def test_valor_duas_casas():
    inf = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA), valor=1262.9))
    assert _txt(inf, "valores/vServPrest/vServ") == "1262.90"


def test_simples_usa_ptottribsn():
    inf = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA)))
    tot = inf.find(f"{{{NS}}}valores/{{{NS}}}trib/{{{NS}}}totTrib")
    filhos = [etree.QName(c).localname for c in tot]
    assert filhos == ["pTotTribSN"]              # E0712: Simples não usa indTotTrib


def test_nao_optante_usa_indtottrib():
    d = dict(CONFIG_VALIDA)
    d = ClienteConfig.from_dict({**CONFIG_VALIDA,
                                 "prestador": {**CONFIG_VALIDA["prestador"],
                                               "regime": {"opSimpNac": 1}}})
    inf = _inf(_montar(d))
    tot = inf.find(f"{{{NS}}}valores/{{{NS}}}trib/{{{NS}}}totTrib")
    assert [etree.QName(c).localname for c in tot] == ["indTotTrib"]

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
    # a implementação de referência em PHP (prestadores com inscrição municipal).
    cfg = ClienteConfig.from_dict({**CONFIG_VALIDA,
                                   "prestador": {**CONFIG_VALIDA["prestador"],
                                                 "inscricao_municipal": "12345678"}})
    prest = _inf(_montar(cfg)).find(f"{{{NS}}}prest")
    assert [etree.QName(c).localname for c in prest] == ["CNPJ", "IM", "regTrib"]
    assert prest.find(f"{{{NS}}}IM").text == "12345678"


def test_prestador_sem_im_omite_o_elemento():
    # A IM é OPCIONAL e quem manda é o CNC do município, POR CNPJ (§10): quando o CNPJ não tem
    # IM no CNC, informá-la dá E0120 ("IM não deve ser informada..."). Config com IM vazia,
    # nula ou ausente => o <IM> NÃO sai do XML. Regressão de produção: municípios sem CNC e
    # CNPJs sem IM dentro de município COM CNC emitem limpo justamente por essa omissão.
    for valor in (None, "", "   "):
        cfg = ClienteConfig.from_dict({**CONFIG_VALIDA,
                                       "prestador": {**CONFIG_VALIDA["prestador"],
                                                     "inscricao_municipal": valor}})
        prest = _inf(_montar(cfg)).find(f"{{{NS}}}prest")
        assert prest.find(f"{{{NS}}}IM") is None, f"IM não deveria sair para {valor!r}"
        assert [etree.QName(c).localname for c in prest] == ["CNPJ", "regTrib"]


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
    tom = {                                          # dados FICTÍCIOS (CNPJ de teste, mód-11 ok)
        "cpf_cnpj": "11222333000181", "nome": "EMPRESA TOMADORA EXEMPLO LTDA",
        "im": "12345",
        "endereco": {"cep": "01000-000", "logradouro": "RUA EXEMPLO",
                     "numero": "52", "bairro": "CENTRO", "cMun": "3550308"},
        "fone": "(11) 5555-1234", "email": "contato@exemplo.com.br",
    }
    toma = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA), tomador=tom)).find(f"{{{NS}}}toma")
    assert [etree.QName(c).localname for c in toma] == \
        ["CNPJ", "IM", "xNome", "end", "fone", "email"]
    assert toma.find(f"{{{NS}}}fone").text == "1155551234"        # só dígitos
    assert toma.find(f"{{{NS}}}email").text == "contato@exemplo.com.br"
    # <end> nacional, ordem interna: endNac(cMun, CEP) → xLgr → nro → xBairro (sem xCpl aqui)
    end = toma.find(f"{{{NS}}}end")
    assert [etree.QName(c).localname for c in end] == ["endNac", "xLgr", "nro", "xBairro"]
    endnac = end.find(f"{{{NS}}}endNac")
    assert [etree.QName(c).localname for c in endnac] == ["cMun", "CEP"]
    assert endnac.find(f"{{{NS}}}cMun").text == "3550308"
    assert endnac.find(f"{{{NS}}}CEP").text == "01000000"         # CEP sem traço, 8 díg
    assert end.find(f"{{{NS}}}xLgr").text == "RUA EXEMPLO"
    assert end.find(f"{{{NS}}}nro").text == "52"
    assert end.find(f"{{{NS}}}xBairro").text == "CENTRO"


def test_tomador_endereco_com_complemento():
    tom = {"cpf_cnpj": "11222333000181", "nome": "X",
           "endereco": {"cep": "01000000", "logradouro": "RUA A", "numero": "10",
                        "complemento": "Sala 2", "bairro": "CENTRO", "cMun": "3550308"}}
    end = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA),
                       tomador=tom)).find(f"{{{NS}}}toma/{{{NS}}}end")
    assert [etree.QName(c).localname for c in end] == ["endNac", "xLgr", "nro", "xCpl", "xBairro"]
    assert end.find(f"{{{NS}}}xCpl").text == "Sala 2"


def test_tomador_endereco_incompleto_e_omitido_atomico():
    # Bloco parcial (sem bairro) = E1235 → omite o endereço INTEIRO (tudo-ou-nada), mas a
    # nota continua válida (CNPJ + xNome). Espelha a implementação de referência em PHP.
    tom = {"cpf_cnpj": "11222333000181", "nome": "X",
           "endereco": {"cep": "01000000", "logradouro": "RUA A", "numero": "10",
                        "cMun": "3550308"}}  # falta xBairro
    toma = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA),
                        tomador=tom)).find(f"{{{NS}}}toma")
    assert toma.find(f"{{{NS}}}end") is None
    assert [etree.QName(c).localname for c in toma] == ["CNPJ", "xNome"]


def test_tomador_sem_extras_xml_inalterado():
    # Sem end/fone/email/IM o <toma> é idêntico ao de antes (só doc + xNome) — garante que a
    # extensão é puramente ADITIVA (o golden, cujo tomador não tem endereço, segue bate-byte).
    toma = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA))).find(f"{{{NS}}}toma")
    assert [etree.QName(c).localname for c in toma] == ["CPF", "xNome"]


def test_info_complementares_vai_no_fim_do_serv():
    # xInfComp (texto livre, sem efeito fiscal) — infoCompl é o ÚLTIMO filho de <serv> (TCServ).
    cfg = ClienteConfig.from_dict(
        {**CONFIG_VALIDA,
         "servico": {**CONFIG_VALIDA["servico"],
                     "info_complementares": "Nao ha retencao de IRRF"}}
    )
    inf = _inf(_montar(cfg))
    serv = inf.find(f"{{{NS}}}serv")
    assert [etree.QName(c).localname for c in serv] == ["locPrest", "cServ", "infoCompl"]
    assert _txt(inf, "serv/infoCompl/xInfComp") == "Nao ha retencao de IRRF"


def test_info_complementares_vazio_omite_o_grupo():
    # Sem texto, nem <infoCompl> nem <xInfComp> (minLength=1): XML idêntico ao de antes.
    inf = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA)))
    serv = inf.find(f"{{{NS}}}serv")
    assert [etree.QName(c).localname for c in serv] == ["locPrest", "cServ"]


def test_info_complementares_trunca_em_2000():
    cfg = ClienteConfig.from_dict(
        {**CONFIG_VALIDA,
         "servico": {**CONFIG_VALIDA["servico"], "info_complementares": "x" * 2500}}
    )
    assert len(_txt(_inf(_montar(cfg)), "serv/infoCompl/xInfComp")) == 2000


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


def test_mei_usa_indtottrib_e_omite_regaptribsn():
    # MEI (opSimpNac=2) é ISENTO do valor aproximado dos tributos (Decreto 8.264/2014):
    # totTrib usa indTotTrib (NÃO pTotTribSN), e o regTrib NÃO leva regApTribSN — igual à nota
    # real do EmissorWeb do gov. O chaveamento é do MOTOR: mesmo com regApTribSN no config
    # (default do RegimeConfig é 1), o MEI o omite. Regressão do primeiro MEI em produção.
    cfg = ClienteConfig.from_dict({**CONFIG_VALIDA,
                                   "prestador": {**CONFIG_VALIDA["prestador"],
                                                 "regime": {"opSimpNac": 2, "regApTribSN": 1,
                                                            "regEspTrib": 0}}})
    inf = _inf(_montar(cfg))
    reg = inf.find(f"{{{NS}}}prest/{{{NS}}}regTrib")
    assert [etree.QName(c).localname for c in reg] == ["opSimpNac", "regEspTrib"]
    trib = inf.find(f"{{{NS}}}valores/{{{NS}}}trib")
    # E0676: MEI NÃO pode ter tribFed (PIS/COFINS) — só tribMun + totTrib(indTotTrib).
    assert [etree.QName(c).localname for c in trib] == ["tribMun", "totTrib"]
    tot = trib.find(f"{{{NS}}}totTrib")
    assert [etree.QName(c).localname for c in tot] == ["indTotTrib"]


def test_piscofins_cst_default_e_override():
    # CST do PIS/COFINS: o default do motor é "08" (Operação sem Incidência) e é aceito pelo
    # SEFIN, mas há contribuintes cujo portal emite "00" (Nenhum) — a fonte da verdade é o XML
    # que o próprio contribuinte já emitiu (§12). Portanto: precisa ser configurável.
    inf = _inf(_montar(ClienteConfig.from_dict(CONFIG_VALIDA)))
    assert _txt(inf, "valores/trib/tribFed/piscofins/CST") == "08"

    cfg = ClienteConfig.from_dict({
        **CONFIG_VALIDA,
        "servico": {**CONFIG_VALIDA["servico"],
                    "tributos": {**CONFIG_VALIDA["servico"]["tributos"], "piscofins_cst": "00"}},
    })
    assert _txt(_inf(_montar(cfg)), "valores/trib/tribFed/piscofins/CST") == "00"


def test_endereco_incompleto_do_tomador_avisa_no_log(caplog):
    # A omissão atômica do <end> não pode ser SILENCIOSA: sem aviso, a nota sai "com sucesso"
    # sem o endereço que o chamador achou que tinha mandado. O log diz QUAIS campos faltaram —
    # e não vaza valor nenhum (nada de CEP/logradouro do tomador no log).
    tom = {"cpf_cnpj": "11222333000181", "nome": "X",
           "endereco": {"cep": "01000000", "logradouro": "RUA EXEMPLO", "numero": "10",
                        "cMun": "3550308"}}  # falta xBairro
    with caplog.at_level("WARNING", logger="pynfsenacional.dps"):
        _montar(ClienteConfig.from_dict(CONFIG_VALIDA), tomador=tom)
    assert "bairro" in caplog.text and "OMITIDO" in caplog.text
    assert "RUA EXEMPLO" not in caplog.text and "01000000" not in caplog.text

"""Montagem da DPS (Declaração de Prestação de Serviço) — o XML que é assinado e
enviado. Aqui mora TODA a lógica fiscal (docs/conhecimento-fiscal.md §4).

Regras-chave (E-codes):
  • cTribNac (6 díg) + cTribMun — sem o municipal, E0312.
  • prestador=emitente (tpEmit=1): NÃO enviar nome nem endereço — E0128/E0121.
  • Simples: usar totTrib/pTotTribSN, nunca indTotTrib — E0712.
  • totTrib é sempre obrigatório — E1235.
  • verAplic ≤ 20 chars — E1235.
  • fuso America/Sao_Paulo ao gerar dhEmi — E0008 (módulo relogio).
  • tomador identificado EXIGE xNome — E1235 (ver §7).

Serialização: construímos o XML com `lxml` na ORDEM EXATA do XSD (AnexoI). O alvo de
corretude NÃO é o byte cru, e sim a **forma canônica (C14N) do `infDPS`** — provada
byte-a-byte idêntica à de uma implementação de referência em PHP (privada; ver tests/golden).
`dhEmi`/`dCompet`/`verAplic` são injetáveis para que o golden seja determinístico.
"""

from __future__ import annotations

from typing import Any

from lxml import etree

from . import documentos
from .config import ClienteConfig

NS = "http://www.sped.fazenda.gov.br/nfse"
VER_APLIC = "PyNFSeNacional-0.1"   # ≤ 20 chars (TSVerAplic / E1235)
# Leiaute da DPS. 1.01 = layout RTC (NT 004 v2.0 / NT 007). Há revisão OFICIAL do XSD v1.01 cujo
# TVerNFSe casa SÓ "1.01" (rejeita "1.00"); "1.01" é aceito por todas as revisões — o bump é
# defensivo para as validações RTC obrigatórias em 03/08/2026. Validado em homologação e em
# emissão de produção real (notas emitidas em 1.01 e canceladas). O grupo IBSCBS segue OPCIONAL
# no schema (minOccurs=0) e o Simples é DISPENSADO do destaque IBS/CBS em 2026 → o montador NÃO
# emite o grupo. O atributo `versao` fica na raiz <DPS>, FORA do infDPS assinado → o C14N/
# DigestValue e o golden não mudam (a paridade com a implementação PHP de referência segue intacta).
VERSAO_DPS = "1.01"


def _el(parent: etree._Element, tag: str, texto: str | None = None) -> etree._Element:
    el = etree.SubElement(parent, f"{{{NS}}}{tag}")
    if texto is not None:
        el.text = texto
    return el


def id_dps(cfg: ClienteConfig, numero: str, serie: str = "1") -> str:
    """`Id` da DPS (45 chars) — porta `IdGenerator::generateDpsId` do PHP.
    Formato: DPS + IBGE(7) + tipoInscr(1: 2=CNPJ/1=CPF) + inscrFed(14) + série(5) + nDPS(15).
    Determinístico — base da idempotência (verificarDps)."""
    doc = documentos.digitos(cfg.prestador.cnpj)
    tipo = "2" if len(doc) == 14 else "1"
    return (
        "DPS"
        + cfg.prestador.codigo_municipio[:7]
        + tipo
        + doc.zfill(14)
        + str(serie).zfill(5)
        + str(numero).zfill(15)
    )


def _montar_end_toma(toma: etree._Element, end: Any) -> None:
    """Anexa o bloco ``<end>`` (TCEndereco nacional) ao ``<toma>``/``<interm>``, na ordem
    EXATA do XSD: ``endNac(cMun, CEP) → xLgr → nro → xCpl? → xBairro``.

    BLOCO ATÔMICO (tudo-ou-nada): se faltar qualquer obrigatório (cMun 7 díg, CEP 8 díg,
    logradouro, bairro), OMITE o endereço inteiro — um bloco parcial é E1235. Mesma regra
    do ``gt_montar_endereco``/``montarEnderecoTcEndereco`` do motor PHP de referência.
    ``nro`` cai para 'S/N' quando vazio. Endereço no exterior (endExt) não é coberto aqui.
    """
    if not isinstance(end, dict) or not end:
        return
    cmun = documentos.digitos(end.get("cMun") or end.get("codigo_municipio") or end.get("ibge"))
    cep = documentos.digitos(end.get("cep") or end.get("CEP"))
    xlgr = str(end.get("logradouro") or end.get("xLgr") or "").strip()
    bairro = str(end.get("bairro") or end.get("xBairro") or "").strip()
    nro = str(end.get("numero") or end.get("nro") or "").strip() or "S/N"
    if len(cmun) != 7 or len(cep) != 8 or not xlgr or not bairro:
        return  # parcial = E1235 → omite o endereço inteiro (atômico, igual ao PHP)
    el_end = _el(toma, "end")
    endnac = _el(el_end, "endNac")
    _el(endnac, "cMun", cmun)
    _el(endnac, "CEP", cep)
    _el(el_end, "xLgr", xlgr[:255])
    _el(el_end, "nro", nro[:60])
    cpl = str(end.get("complemento") or end.get("xCpl") or "").strip()
    if cpl:
        _el(el_end, "xCpl", cpl[:156])
    _el(el_end, "xBairro", bairro[:60])


def montar_dps(
    cfg: ClienteConfig, *, numero: str, valor: float, descricao: str,
    tomador: dict[str, Any] | None, ambiente: str, serie: str = "1",
    dh_emi: str | None = None, d_comp: str | None = None, ver_aplic: str | None = None,
) -> str:
    """Monta o XML da DPS (string, NÃO assinado) a partir da config + dados da emissão.

    `tomador`: {"cpf_cnpj": "...", "nome": "..."} ou None (consumidor final → omite <toma>).
        Campos OPCIONAIS (entram no <toma> quando presentes, na ordem do XSD): "im",
        "fone"/"telefone", "email", e "endereco" (bloco atômico — ver _montar_end_toma).
    `ambiente`: "homologacao" (tpAmb=2) | "producao" (tpAmb=1).
    `dh_emi`/`d_comp`/`ver_aplic`: injetáveis (default = relógio de Brasília / constante);
    o golden passa valores fixos para o byte-diff ser determinístico.
    """
    from . import relogio  # import tardio: relogio é infra, evita ciclo conceitual

    p, s, r = cfg.prestador, cfg.servico, cfg.prestador.regime
    idd = id_dps(cfg, numero, serie)

    dps = etree.Element(f"{{{NS}}}DPS", nsmap={None: NS})
    dps.set("versao", VERSAO_DPS)
    inf = _el(dps, "infDPS")
    inf.set("Id", idd)

    _el(inf, "tpAmb", "2" if ambiente == "homologacao" else "1")
    _el(inf, "dhEmi", dh_emi or relogio.dh_emi())
    _el(inf, "verAplic", ver_aplic or VER_APLIC)
    _el(inf, "serie", str(serie))
    _el(inf, "nDPS", str(numero))
    _el(inf, "dCompet", d_comp or relogio.d_comp())
    _el(inf, "tpEmit", "1")                       # prestador é o emitente
    _el(inf, "cLocEmi", p.codigo_municipio)

    # Prestador (tpEmit=1): CNPJ + (IM) + regTrib — sem nome/endereço (E0128/E0121).
    # ORDEM DO XSD (AnexoI): a IM (Inscrição Municipal) vem ANTES do regTrib. Emiti-la depois
    # gera E1235 (falha de schema) para qualquer prestador que tenha IM — pegado pelo diff
    # byte-a-byte contra o motor PHP de produção (clientes 14/229/86, que têm IM).
    prest = _el(inf, "prest")
    _el(prest, "CNPJ", documentos.digitos(p.cnpj))
    if p.inscricao_municipal:
        _el(prest, "IM", documentos.digitos(p.inscricao_municipal))
    reg = _el(prest, "regTrib")
    _el(reg, "opSimpNac", str(r.opSimpNac))
    if r.regApTribSN is not None:
        _el(reg, "regApTribSN", str(r.regApTribSN))
    _el(reg, "regEspTrib", str(r.regEspTrib))

    # Tomador (opcional): só com documento; identificado EXIGE xNome (§7).
    # ORDEM DO XSD (TSDestinaDps, AnexoI B-34..B-46): CPF|CNPJ → IM → xNome → end → fone → email.
    # Trocar a ordem (ex.: email antes de end) = E1235. Tudo abaixo de xNome é OPCIONAL: end/
    # fone/email só entram quando vierem nos dados → sem eles o XML é IDÊNTICO ao de antes (o
    # golden, cujo tomador não tem endereço, segue bate-byte). Espelha o buildTomador do PHP.
    tom = tomador or {}
    doc = documentos.digitos(tom.get("cpf_cnpj") or tom.get("cpf") or tom.get("cnpj"))
    if doc:
        toma = _el(inf, "toma")
        _el(toma, "CNPJ" if len(doc) == 14 else "CPF", doc)
        im = documentos.digitos(tom.get("im") or tom.get("inscricao_municipal"))
        if im:
            _el(toma, "IM", im)
        nome = (tom.get("nome") or tom.get("xNome") or "").strip()
        if nome:
            _el(toma, "xNome", nome)
        _montar_end_toma(toma, tom.get("endereco") or tom.get("end"))
        fone = documentos.digitos(tom.get("fone") or tom.get("telefone"))
        if fone:
            _el(toma, "fone", fone)
        email = (tom.get("email") or "").strip()
        if email:
            _el(toma, "email", email[:80])

    # Serviço: local da prestação + código (par cTribNac+cTribMun) + descrição.
    serv = _el(inf, "serv")
    lp = _el(serv, "locPrest")
    _el(lp, "cLocPrestacao", s.codigo_municipio_prestacao)
    cserv = _el(serv, "cServ")
    _el(cserv, "cTribNac", s.cTribNac)
    if s.cTribMun:
        _el(cserv, "cTribMun", str(s.cTribMun))
    _el(cserv, "xDescServ", descricao or s.descricao_padrao)

    # Valores e tributos.
    valores = _el(inf, "valores")
    vsp = _el(valores, "vServPrest")
    _el(vsp, "vServ", f"{float(valor):.2f}")
    trib = _el(valores, "trib")
    tm = _el(trib, "tribMun")
    _el(tm, "tribISSQN", str(s.tributos.get("tribISSQN", 1)))
    _el(tm, "tpRetISSQN", str(s.tributos.get("tpRetISSQN", 1)))
    tf = _el(trib, "tribFed")
    pc = _el(tf, "piscofins")
    _el(pc, "CST", str(s.tributos.get("piscofins_cst", "08")))
    tt = _el(trib, "totTrib")
    if r.opSimpNac == 1:   # Não Optante usa indTotTrib; Simples (MEI/ME-EPP) usa pTotTribSN
        _el(tt, "indTotTrib", str(s.tributos.get("indTotTrib", 0)))
    else:
        _el(tt, "pTotTribSN", str(s.tributos.get("pTotTribSN", "0.00")))

    return str(etree.tostring(dps, encoding="unicode"))

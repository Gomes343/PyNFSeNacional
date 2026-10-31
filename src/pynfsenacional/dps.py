"""Montagem da DPS (Declaração de Prestação de Serviço) — o XML que é assinado e
enviado. Aqui mora TODA a lógica fiscal (docs/conhecimento-fiscal.md §4).

Regras-chave (E-codes):
  • cTribNac (6 díg) + cTribMun — sem o municipal, E0312.
  • prestador=emitente (tpEmit=1): NÃO enviar nome nem endereço — E0128/E0121.
  • ME/EPP optante do Simples (opSimpNac=3): totTrib/pTotTribSN, nunca indTotTrib — E0712.
  • MEI (opSimpNac=2): ISENTO do valor aproximado dos tributos (Decreto 8.264/2014) →
    totTrib/indTotTrib=0 (NÃO pTotTribSN), regTrib SEM regApTribSN, e SEM o bloco tribFed
    (E0676: MEI não pode preencher tributos federais — recolhe no DAS-SIMEI) — como o EmissorWeb.
  • regApTribSN é EXCLUSIVO do ME/EPP: Não Optante e MEI que o informam levam E0162.
  • Regime Regular (opSimpNac=1, §14): cNBS, tpRetPisCofins, totTrib/pTotTrib e o grupo IBSCBS
    — todos OPCIONAIS por config; sem eles a DPS sai exatamente como antes.
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

import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from lxml import etree

from . import documentos
from .config import PTOTTRIB_CHAVES, ClienteConfig, percentual

_log = logging.getLogger(__name__)

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


def valor_decimal(valor: Decimal | float | int | str) -> Decimal:
    """O valor do serviço em `Decimal` com 2 casas (arredondamento comercial).

    Aceita Decimal, int, str ("1.262,90" pt-BR ou "1262.90") e float — o float passa por
    `str()` antes, para não carregar o erro binário (2.675 vira 2.68, não 2.67)."""
    if isinstance(valor, bool):
        raise ValueError(f"valor inválido: {valor!r}")
    if isinstance(valor, str):
        texto = valor.strip().replace("R$", "").strip()
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = str(valor)
    try:
        d = Decimal(texto)
    except InvalidOperation:
        raise ValueError(f"valor inválido: {valor!r}") from None
    if not d.is_finite():
        raise ValueError(f"valor inválido: {valor!r}")
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _el(parent: etree._Element, tag: str, texto: str | None = None) -> etree._Element:
    el = etree.SubElement(parent, f"{{{NS}}}{tag}")
    if texto is not None:
        el.text = texto
    return el


def id_dps(cfg: ClienteConfig, numero: str, serie: str = "1") -> str:
    """`Id` da DPS (45 chars) — porta `IdGenerator::generateDpsId` do PHP.
    Formato: DPS + IBGE(7) + tipoInscr(1: 2=CNPJ/1=CPF) + inscrFed(14) + série(5) + nDPS(15).
    Determinístico — base da idempotência (verificarDps)."""
    doc = documentos.norm_documento(cfg.prestador.cnpj)  # CNPJ alfanumérico: preserva letras
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
    da implementação de referência em PHP. ``nro`` cai para 'S/N' quando vazio. Endereço no
    exterior (``endExt``) não é coberto aqui.

    A omissão é REGISTRADA em log (nível WARNING, só os NOMES dos campos que faltaram — nunca
    o valor): descartar o endereço em silêncio faz a nota sair "com sucesso" sem o dado que o
    chamador achou que tinha mandado.
    """
    if not isinstance(end, dict) or not end:
        return
    campos, faltando = documentos.endereco_nacional(end)   # a MESMA regra do validador (E0237)
    if faltando:
        # Parcial = E1235 → omite o endereço INTEIRO (atômico). Avisa: guarda calada vira nota
        # emitida "com sucesso" sem o endereço que o chamador achou que tinha mandado.
        _log.warning(
            "endereço do tomador OMITIDO da DPS: faltam %s (o bloco <end> é tudo-ou-nada)",
            ", ".join(faltando),
        )
        return
    el_end = _el(toma, "end")
    endnac = _el(el_end, "endNac")
    _el(endnac, "cMun", campos["cMun"])
    _el(endnac, "CEP", campos["CEP"])
    _el(el_end, "xLgr", campos["xLgr"][:255])
    _el(el_end, "nro", campos["nro"][:60])
    if campos["xCpl"]:
        _el(el_end, "xCpl", campos["xCpl"][:156])
    _el(el_end, "xBairro", campos["xBairro"][:60])


def montar_dps(
    cfg: ClienteConfig, *, numero: str, valor: Decimal | float | int | str, descricao: str,
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
    # byte-a-byte contra a implementação PHP de referência (prestadores que têm IM).
    prest = _el(inf, "prest")
    _el(prest, "CNPJ", documentos.norm_documento(p.cnpj))  # CNPJ alfanumérico: preserva letras
    # A IM só entra se sobrar DÍGITO depois da limpeza: string vazia/em branco emitiria um
    # <IM></IM> vazio (falha de schema), e a IM é opcional — quem decide se ela vai é o CNC
    # do município, POR CNPJ (E0116 × E0120; ver docs §10).
    im_prest = documentos.digitos(p.inscricao_municipal)
    if im_prest:
        _el(prest, "IM", im_prest)
    reg = _el(prest, "regTrib")
    _el(reg, "opSimpNac", str(r.opSimpNac))
    # regApTribSN (regime de apuração do SN) só se aplica a ME/EPP optante (opSimpNac=3).
    # MEI (2) e Não Optante (1) NÃO o informam — E0162 ("não é permitido ao não optante e ao MEI
    # preencherem o regime de apuração"). O chaveamento é do motor: o default 1 da dataclass não
    # pode vazar para quem não é ME/EPP (§3).
    if r.opSimpNac == 3 and r.regApTribSN is not None:
        _el(reg, "regApTribSN", str(r.regApTribSN))
    _el(reg, "regEspTrib", str(r.regEspTrib))

    # Tomador (opcional): só com documento; identificado EXIGE xNome (§7).
    # ORDEM DO XSD (TSDestinaDps, AnexoI B-34..B-46): CPF|CNPJ → IM → xNome → end → fone → email.
    # Trocar a ordem (ex.: email antes de end) = E1235. Tudo abaixo de xNome é OPCIONAL: end/
    # fone/email só entram quando vierem nos dados → sem eles o XML é IDÊNTICO ao de antes (o
    # golden, cujo tomador não tem endereço, segue bate-byte). Espelha o buildTomador do PHP.
    tom = tomador or {}
    # CNPJ alfanumérico do tomador: preserva letras; CPF (só dígitos) sai igual.
    doc = documentos.norm_documento(tom.get("cpf_cnpj") or tom.get("cpf") or tom.get("cnpj"))
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
    # Item da NBS (TCCServ: cTribNac → cTribMun? → xDescServ → cNBS? → cIntContrib?). Opcional:
    # vazio omite — a DPS do Simples segue idêntica (§14).
    nbs = documentos.digitos(s.cNBS)
    if nbs:
        _el(cserv, "cNBS", nbs)
    # infoCompl (0-1) é o ÚLTIMO filho de <serv> no XSD (TCServ) — depois de locPrest/cServ e de
    # comExt/obra/atvEvento/explRod, que não emitimos. Texto livre, sem efeito fiscal: o SEFIN não
    # o interpreta e o DANFSe o imprime como "Inf. Cont.:". Vazio → o grupo inteiro é OMITIDO
    # (um <infoCompl/> sem filho é falha de schema, e xInfComp tem minLength=1).
    info_compl = (s.info_complementares or "").strip()
    if info_compl:
        _el(_el(serv, "infoCompl"), "xInfComp", info_compl[:2000])  # TSDescInfCompl: 1-2000

    # Valores e tributos.
    valores = _el(inf, "valores")
    vsp = _el(valores, "vServPrest")
    _el(vsp, "vServ", str(valor_decimal(valor)))
    trib = _el(valores, "trib")
    tm = _el(trib, "tribMun")
    _el(tm, "tribISSQN", str(s.tributos.get("tribISSQN", 1)))
    _el(tm, "tpRetISSQN", str(s.tributos.get("tpRetISSQN", 1)))
    # tribFed (PIS/COFINS): PROIBIDO para o MEI — E0676 ("não é permitido preencher os tributos
    # federais quando o emitente é MEI"). O MEI recolhe tudo no DAS-SIMEI. Só ME/EPP e Não Optante
    # enviam tribFed. (tribFed é minOccurs=0 no XSD; a nota real do MEI no EmissorWeb sai sem ele.)
    if r.opSimpNac != 2:
        tf = _el(trib, "tribFed")
        pc = _el(tf, "piscofins")
        _el(pc, "CST", str(s.tributos.get("piscofins_cst", "08")))
        # tpRetPisCofins é o ÚLTIMO filho de piscofins (depois de vBCPisCofins/pAliq*/vPis/vCofins,
        # que não emitimos). Obrigatório quando o CST é tributável (E0698); sem ele, omitido (§12).
        tprp = s.tributos.get("tpRetPisCofins")
        if tprp is not None and str(tprp).strip():
            _el(pc, "tpRetPisCofins", str(tprp).strip())
    tt = _el(trib, "totTrib")
    # totTrib (choice) depende do regime tributário:
    #  • Não Optante (1) e MEI (2): indTotTrib. O MEI é ISENTO de declarar o valor aproximado dos
    #    tributos (Decreto 8.264/2014) — a nota real do EmissorWeb sai com indTotTrib=0.
    #  • ME/EPP optante do Simples (3): pTotTribSN (% total aprox. — Lei da Transparência).
    #    E0712 PROÍBE indTotTrib para ME/EPP.
    #  • Não Optante (1) com `pTotTrib` configurado: o percentual aproximado em três parcelas
    #    (federal/estadual/municipal) — o que o portal emite para o Regime Regular (§14).
    ptt = s.tributos.get("pTotTrib")
    if r.opSimpNac == 1 and isinstance(ptt, dict) and ptt:
        g = _el(tt, "pTotTrib")
        for chave in PTOTTRIB_CHAVES:
            _el(g, chave, _dec2(ptt.get(chave), f"servico.tributos.pTotTrib.{chave}"))
    elif r.opSimpNac in (1, 2):
        _el(tt, "indTotTrib", str(s.tributos.get("indTotTrib", 0)))
    else:
        _el(tt, "pTotTribSN", str(s.tributos.get("pTotTribSN", "0.00")))

    # Grupo IBS/CBS (§8): último filho do infDPS, depois de <valores>. Só a CLASSIFICAÇÃO da
    # operação — base, alíquotas e valores o SEFIN calcula. Sem `servico.ibscbs`, omitido.
    if s.ibscbs:
        _montar_ibscbs(inf, s.ibscbs)

    return str(etree.tostring(dps, encoding="unicode"))


def _dec2(valor: Any, nome: str) -> str:
    """Percentual com 2 casas (TSDec3V2). Ausente/não numérico levanta — escrever 0.00 no lugar
    seria declarar um tributo que ninguém informou."""
    v = percentual(valor)
    if v is None:
        raise ValueError(f"{nome}: percentual ausente ou não numérico ({valor!r})")
    return f"{v:.2f}"


def _montar_ibscbs(inf: etree._Element, ibs: dict[str, Any]) -> None:
    """Grupo IBSCBS na ordem do XSD (TCRTCInfoIBSCBS): finNFSe → indFinal? → cIndOp → indDest
    → valores/trib/gIBSCBS(CST → cClassTrib). Os opcionais não cobertos (tpOper, gRefNFSe,
    tpEnteGov, dest, imovel, gReeRepRes, cCredPres, gTribRegular, gDif) o validar() recusa."""
    def obrig(chave: str) -> str:
        v = str(ibs.get(chave) or "").strip()
        if not v:
            raise ValueError(f"servico.ibscbs.{chave} é obrigatório no grupo IBS/CBS")
        return v

    g = _el(inf, "IBSCBS")
    _el(g, "finNFSe", str(ibs.get("finNFSe", "0")).strip())
    if ibs.get("indFinal") is not None and str(ibs["indFinal"]).strip():
        _el(g, "indFinal", str(ibs["indFinal"]).strip())
    _el(g, "cIndOp", obrig("cIndOp"))
    _el(g, "indDest", str(ibs.get("indDest", "0")).strip())
    gi = _el(_el(_el(g, "valores"), "trib"), "gIBSCBS")
    _el(gi, "CST", obrig("CST"))
    _el(gi, "cClassTrib", obrig("cClassTrib"))

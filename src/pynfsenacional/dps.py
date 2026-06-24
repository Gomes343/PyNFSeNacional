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
VERSAO_DPS = "1.00"


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


def montar_dps(
    cfg: ClienteConfig, *, numero: str, valor: float, descricao: str,
    tomador: dict[str, Any] | None, ambiente: str, serie: str = "1",
    dh_emi: str | None = None, d_comp: str | None = None, ver_aplic: str | None = None,
) -> str:
    """Monta o XML da DPS (string, NÃO assinado) a partir da config + dados da emissão.

    `tomador`: {"cpf_cnpj": "...", "nome": "..."} ou None (consumidor final → omite <toma>).
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

    # Prestador (tpEmit=1): SÓ CNPJ + regTrib — sem nome/endereço (E0128/E0121).
    prest = _el(inf, "prest")
    _el(prest, "CNPJ", documentos.digitos(p.cnpj))
    reg = _el(prest, "regTrib")
    _el(reg, "opSimpNac", str(r.opSimpNac))
    if r.regApTribSN is not None:
        _el(reg, "regApTribSN", str(r.regApTribSN))
    _el(reg, "regEspTrib", str(r.regEspTrib))
    if p.inscricao_municipal:
        _el(prest, "IM", documentos.digitos(p.inscricao_municipal))

    # Tomador (opcional): só com documento; identificado EXIGE xNome (§7).
    doc = documentos.digitos(
        (tomador or {}).get("cpf_cnpj") or (tomador or {}).get("cpf") or (tomador or {}).get("cnpj")
    )
    if doc:
        toma = _el(inf, "toma")
        _el(toma, "CNPJ" if len(doc) == 14 else "CPF", doc)
        nome = ((tomador or {}).get("nome") or (tomador or {}).get("xNome") or "").strip()
        if nome:
            _el(toma, "xNome", nome)

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

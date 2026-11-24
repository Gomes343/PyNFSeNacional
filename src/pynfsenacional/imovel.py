"""Operações com BEM IMÓVEL no grupo IBS/CBS — a leitura ÚNICA para a DPS e para a validação.

O grupo ``IBSCBS/imovel`` (docs §23) identifica o imóvel da operação e, na LOCAÇÃO (cTribNac
99.03.xx), leva o que a reforma tributária deixa fora da base do IBS/CBS:

  • ``cMun``: o município do imóvel (todas as unidades da operação ficam nele);
  • ``gLocacao`` (só 99.03): percentual de copropriedade, valor total da operação, vencimento
    original — com ``vServ = pCopropriedade × vTotOper`` (E0433);
  • ``gUnidImob`` (até 99): cada unidade imobiliária, pelo CIB **ou** pelo endereço (o XSD dá a
    escolha), com a inscrição do IPTU opcional e os AJUSTES da base (até 1000 por unidade):
    01 tributos do imóvel (IPTU), 02 emolumento, 03 condomínio, 04 REDUTOR SOCIAL (só aluguel
    residencial, NBS 1.1002.10.00), 99 outros (com descrição).

A redução de 70% da alíquota da locação NÃO vai aqui: vem do ``cClassTrib`` (200027, CST 200), e
o SEFIN calcula. A lib não calcula o redutor (R$ 600 corrigidos pelo IPCA): o valor é do chamador.

No leiaute de PRODUÇÃO (09/02/2026) o grupo é só a identificação de UM imóvel (inscrição + CIB ou
endereço); locação e ajustes não existem nele (ver ``no_leiaute_de_producao``).

Aqui só se lê e se confere; a ordem dos elementos é do ``dps.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any

#: cIndOp de operações com imóvel (Anexo I, RN 603/604): com eles o grupo ``imovel`` é obrigatório
#: (E0932); sem eles, proibido (E0928) — salvo os subitens de OBRA abaixo, que levam ``serv/obra``.
IND_OP_IMOVEL = ("020101", "020201", "020202", "020301", "020401")
#: Destes, os que exigem ao menos uma unidade imobiliária (RN 613, E0938).
IND_OP_EXIGE_UNIDADE = ("020101", "020201", "020301")
#: Subitens da construção civil fora das RN 603/604 (a obra se identifica em ``serv/obra``).
CTRIB_OBRA = ("070201", "070202", "070401", "070501", "070502", "070601", "070602", "070701",
              "070801", "071701", "071901")

#: NBS da locação (Anexo B): o redutor social é só do residencial (E0944); 01–03 só nos dois.
NBS_LOCACAO_RESIDENCIAL = "110021000"
NBS_LOCACAO_NAO_RESIDENCIAL = "110022000"

#: tpAjusteBCLocImoveis: parcelas que não integram a base do IBS/CBS na locação.
AJUSTES = {
    "01": "tributos do imóvel inclusos no aluguel (IPTU, contribuição de melhoria)",
    "02": "emolumento incluso no aluguel",
    "03": "condomínio incluso no aluguel",
    "04": "redutor social",
    "99": "outras parcelas inclusas no aluguel",
}
AJUSTE_REDUTOR_SOCIAL = "04"
AJUSTE_OUTROS = "99"

MAX_UNIDADES = 99
MAX_AJUSTES = 1000

_CIB = re.compile(r"[0-9A-Za-z]{8}")
_MUN = re.compile(r"[0-9]{7}")
_CEP = re.compile(r"[0-9]{8}")
_CENTAVO = Decimal("0.01")


@dataclass(frozen=True)
class Ajuste:
    tipo: str
    valor: Decimal
    descricao: str = ""


@dataclass(frozen=True)
class Unidade:
    inscricao: str = ""
    cib: str = ""
    endereco: dict[str, str] = field(default_factory=dict)   # cep, logradouro, numero, ...
    ajustes: tuple[Ajuste, ...] = ()


@dataclass(frozen=True)
class Locacao:
    copropriedade: Decimal          # percentual: 100 = um locador só
    valor_total: Decimal            # vTotOper
    vencimento_original: str = ""   # AAAA-MM-DD, só informativo


@dataclass(frozen=True)
class Imovel:
    codigo_municipio: str
    locacao: Locacao | None
    unidades: tuple[Unidade, ...]


def _txt(d: dict[str, Any], *chaves: str) -> str:
    for c in chaves:
        v = d.get(c)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _dec(valor: Any) -> Decimal | None:
    if valor is None or isinstance(valor, bool) or str(valor).strip() == "":
        return None
    try:
        d = Decimal(str(valor).strip().replace(",", "."))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def e_locacao(c_trib_nac: str) -> bool:
    """Subitem 99.03 (locação, cessão onerosa, arrendamento de bem imóvel)?"""
    return re.sub(r"\D", "", c_trib_nac or "").startswith("9903")


def ler(imovel: dict[str, Any], valor_nota: Decimal) -> tuple[Imovel | None, list[str]]:
    """O dict do chamador → ``Imovel`` + problemas de FORMA. O valor total da locação, quando não
    vem, é o da nota (um locador só: ``vServ = 100% × vTotOper``)."""
    problemas: list[str] = []
    if not isinstance(imovel, dict):
        return None, [f"imovel deve ser um objeto; recebido {type(imovel).__name__}"]
    mun = _txt(imovel, "codigo_municipio", "cMun")
    if not _MUN.fullmatch(mun):
        problemas.append(f"E0929: imovel.codigo_municipio deve ser o código IBGE (7 dígitos); "
                         f"recebido {mun!r}")

    loc: Locacao | None = None
    bruto_loc = imovel.get("locacao")
    if bruto_loc is not None:
        if not isinstance(bruto_loc, dict):
            problemas.append("imovel.locacao deve ser um objeto")
        else:
            desconhecidas = sorted(set(bruto_loc) - {"copropriedade", "valor_total",
                                                     "vencimento_original"})
            if desconhecidas:
                problemas.append(
                    f"imovel.locacao: {desconhecidas} não é coberto por esta biblioteca "
                    f"(descontos na locação ainda não) — §23")
            cop = _dec(bruto_loc.get("copropriedade", "100"))
            if cop is None or not (0 < cop <= 100):
                problemas.append(f"E0940: imovel.locacao.copropriedade é um percentual de mais "
                                 f"de 0 até 100; recebido {bruto_loc.get('copropriedade')!r}")
                cop = Decimal("100")
            total = _dec(bruto_loc.get("valor_total"))
            if total is None:
                if cop == 100:
                    total = valor_nota
                else:
                    problemas.append("imovel.locacao.valor_total é obrigatório com copropriedade "
                                     "abaixo de 100% (o valor da nota é a parte do locador)")
                    total = valor_nota
            elif total <= 0:
                problemas.append(f"imovel.locacao.valor_total deve ser maior que zero; "
                                 f"recebido {bruto_loc.get('valor_total')!r}")
            venc = _txt(bruto_loc, "vencimento_original")
            if venc:
                try:
                    date.fromisoformat(venc)
                except ValueError:
                    problemas.append(f"imovel.locacao.vencimento_original deve ser AAAA-MM-DD; "
                                     f"recebido {venc!r}")
            loc = Locacao(copropriedade=cop.quantize(_CENTAVO), valor_total=total,
                          vencimento_original=venc)

    unidades: list[Unidade] = []
    brutas = imovel.get("unidades") or []
    if not isinstance(brutas, list):
        problemas.append("imovel.unidades deve ser uma lista")
        brutas = []
    if len(brutas) > MAX_UNIDADES:
        problemas.append(f"imovel.unidades: no máximo {MAX_UNIDADES} por nota; "
                         f"recebido {len(brutas)}")
    for i, u in enumerate(brutas, 1):
        unidade, probs = _ler_unidade(u, f"imovel.unidades[{i}]")
        problemas += probs
        if unidade is not None:
            unidades.append(unidade)
    return Imovel(codigo_municipio=mun, locacao=loc, unidades=tuple(unidades)), problemas


def _ler_unidade(u: Any, onde: str) -> tuple[Unidade | None, list[str]]:
    if not isinstance(u, dict):
        return None, [f"{onde} deve ser um objeto"]
    problemas: list[str] = []
    insc = _txt(u, "inscricao", "inscImobFisc")
    if len(insc) > 30:
        problemas.append(f"{onde}.inscricao: até 30 caracteres; recebido {len(insc)}")
    cib = _txt(u, "cib", "cCIB")
    end_bruto = u.get("endereco")
    end: dict[str, str] = {}
    if cib:
        if not _CIB.fullmatch(cib):
            problemas.append(f"E0933: {onde}.cib deve ter 8 caracteres (7 + dígito verificador); "
                             f"recebido {cib!r}")
    elif isinstance(end_bruto, dict) and end_bruto:
        end = {
            "cep": re.sub(r"\D", "", _txt(end_bruto, "cep", "CEP")),
            "logradouro": _txt(end_bruto, "logradouro", "xLgr"),
            "numero": _txt(end_bruto, "numero", "nro"),
            "complemento": _txt(end_bruto, "complemento", "xCpl"),
            "bairro": _txt(end_bruto, "bairro", "xBairro"),
        }
        faltando = [c for c in ("cep", "logradouro", "numero") if not end[c]]
        if faltando:
            problemas.append(f"{onde}.endereco: faltam {faltando} (CEP, logradouro e número são "
                             f"obrigatórios)")
        elif not _CEP.fullmatch(end["cep"]):
            problemas.append(f"{onde}.endereco.cep deve ter 8 dígitos; recebido {end['cep']!r}")
    else:
        problemas.append(f"{onde}: identifique a unidade pelo cib OU pelo endereco "
                         f"(cep, logradouro, numero)")

    ajustes: list[Ajuste] = []
    brutos = u.get("ajustes") or []
    if not isinstance(brutos, list):
        problemas.append(f"{onde}.ajustes deve ser uma lista")
        brutos = []
    if len(brutos) > MAX_AJUSTES:
        problemas.append(f"{onde}.ajustes: no máximo {MAX_AJUSTES}; recebido {len(brutos)}")
    for j, a in enumerate(brutos, 1):
        aonde = f"{onde}.ajustes[{j}]"
        if not isinstance(a, dict):
            problemas.append(f"{aonde} deve ser um objeto")
            continue
        tipo = _txt(a, "tipo", "tpAjusteBCLocImoveis").zfill(2)
        if tipo not in AJUSTES:
            problemas.append(f"{aonde}.tipo deve ser um de {sorted(AJUSTES)}; "
                             f"recebido {a.get('tipo')!r}")
        desc = _txt(a, "descricao", "xTpAjusteBCLocImoveis")
        if tipo == AJUSTE_OUTROS and not desc:
            problemas.append(f"E0949: {aonde}.descricao é obrigatória no tipo 99")
        elif tipo != AJUSTE_OUTROS and desc:
            problemas.append(f"E0954: {aonde}.descricao só vai no tipo 99")
        if len(desc) > 150:
            problemas.append(f"{aonde}.descricao: até 150 caracteres")
        v = _dec(a.get("valor", a.get("vAjusteBCLocImoveis")))
        if v is None or v <= 0:
            problemas.append(f"{aonde}.valor deve ser maior que zero; recebido {a.get('valor')!r}")
            continue
        ajustes.append(Ajuste(tipo=tipo, valor=v.quantize(_CENTAVO), descricao=desc))
    return Unidade(inscricao=insc, cib=cib, endereco=end, ajustes=tuple(ajustes)), problemas


def validar_imovel(imovel: dict[str, Any] | None, servico: Any, valor: Any,
                   nt009: bool) -> list[str]:
    """As regras do Anexo I (NT 009) que dá para conferir ANTES de assinar. `servico` é o
    ``config.Servico`` (cTribNac, cNBS, ibscbs). `nt009`: o leiaute da DPS tem o grupo completo.

    As que dependem do grupo existir (E0932, E0937, E0938) só valem no leiaute da NT 009: no de
    produção o SEFIN ainda não as aplica, e barrar aqui pararia a emissão que ele aceita."""
    from .dps import valor_decimal  # import tardio: dps importa este módulo

    ctrib = re.sub(r"\D", "", getattr(servico, "cTribNac", "") or "")
    nbs = re.sub(r"\D", "", getattr(servico, "cNBS", "") or "")
    ibs = getattr(servico, "ibscbs", None) or {}
    ind_op = str(ibs.get("cIndOp") or "").strip() if isinstance(ibs, dict) else ""
    locacao = e_locacao(ctrib)
    obra = ctrib in CTRIB_OBRA
    problemas: list[str] = []

    if locacao and ind_op and not ind_op.startswith("02"):
        problemas.append(f"E0902: na locação (cTribNac 99.03) o cIndOp é um 02XXXX; "
                         f"recebido {ind_op!r}")
    if imovel is None:
        if nt009 and ind_op in IND_OP_IMOVEL and not obra:
            problemas.append(f"E0932: o cIndOp {ind_op} (operação com imóvel) exige o grupo "
                             f"imovel — passe imovel= na emissão (§23)")
        if nt009 and locacao and ibs:
            problemas.append("E0937: a locação (cTribNac 99.03) exige o grupo imovel com a "
                             "locacao — passe imovel= na emissão (§23)")
        return problemas
    if not ibs:
        return problemas + ["imovel só vai dentro do grupo IBS/CBS (servico.ibscbs) — §23"]

    try:
        v_nota = valor_decimal(valor)
    except ValueError:
        return problemas          # o valor inválido já é acusado pelo emitir()
    im, forma = ler(imovel, v_nota)
    problemas += forma
    if im is None:
        return problemas

    if ind_op and ind_op not in IND_OP_IMOVEL and not obra:
        problemas.append(f"E0928: o grupo imovel não cabe com o cIndOp {ind_op!r} (não é "
                         f"operação com imóvel)")
    if nt009 and ind_op in IND_OP_EXIGE_UNIDADE and not im.unidades:
        problemas.append(f"E0938: o cIndOp {ind_op} exige ao menos uma unidade imobiliária "
                         f"(imovel.unidades)")
    if locacao and im.locacao is None:
        problemas.append("E0937: na locação (cTribNac 99.03) o imovel exige o bloco locacao")
    if not locacao and im.locacao is not None:
        problemas.append("E0936: imovel.locacao só vale na locação (cTribNac 99.03)")

    ajustes = [a for u in im.unidades for a in u.ajustes]
    if ajustes and not locacao:
        problemas.append("E0939: ajustes da base só valem na locação (cTribNac 99.03)")
    for a in ajustes:
        if a.tipo == AJUSTE_REDUTOR_SOCIAL and nbs != NBS_LOCACAO_RESIDENCIAL:
            problemas.append(f"E0944: o redutor social (tipo 04) só vale no aluguel RESIDENCIAL "
                             f"(cNBS 1.1002.10.00); o serviço tem {nbs or 'nenhum'}")
        if a.tipo in ("01", "02", "03") and nbs not in (NBS_LOCACAO_RESIDENCIAL,
                                                        NBS_LOCACAO_NAO_RESIDENCIAL):
            problemas.append(f"o ajuste tipo {a.tipo} só vale com a NBS da locação "
                             f"(1.1002.10.00 ou 1.1002.20.00); o serviço tem {nbs or 'nenhum'}")
    if im.locacao is not None:
        loc = im.locacao
        esperado = (loc.copropriedade / 100 * loc.valor_total).quantize(
            _CENTAVO, rounding=ROUND_HALF_EVEN)
        if abs(esperado - v_nota) > _CENTAVO:
            problemas.append(f"E0433: na locação o valor da nota é copropriedade × valor total "
                             f"({loc.copropriedade}% de {loc.valor_total} = {esperado}); "
                             f"a nota tem {v_nota}")
        for a in ajustes:
            if a.valor > loc.valor_total:
                problemas.append(f"E0966: o ajuste tipo {a.tipo} ({a.valor}) passa do valor "
                                 f"total da operação ({loc.valor_total})")
        soma = (sum((a.valor for a in ajustes), Decimal(0)) * loc.copropriedade / 100)
        if soma > v_nota:
            problemas.append(f"E1547: os ajustes da base ({soma.quantize(_CENTAVO)}, na parte do "
                             f"locador) passam do valor da nota ({v_nota})")
    return problemas


def no_leiaute_de_producao(im: Imovel) -> tuple[Unidade | None, list[str]]:
    """O que cabe no grupo ``imovel`` do leiaute de PRODUÇÃO (09/02/2026): UMA unidade, sem
    locação nem ajustes. Devolve a unidade e o que ficou de fora (para o log): em 2026 a base
    do IBS/CBS não se recolhe, e a produção passa à NT 009 em 01/12/2026."""
    fora: list[str] = []
    if im.locacao is not None:
        fora.append("locacao")
    if any(u.ajustes for u in im.unidades):
        fora.append("ajustes da base")
    if len(im.unidades) > 1:
        fora.append(f"{len(im.unidades) - 1} unidade(s) além da primeira")
    return (im.unidades[0] if im.unidades else None), fora

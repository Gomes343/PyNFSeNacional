"""Tomador no EXTERIOR e comércio exterior — a leitura ÚNICA para a DPS e para a validação.

Três peças da DPS, todas opcionais e aditivas (sem elas a DPS sai idêntica à de antes):

  • ``toma``: no lugar do CPF/CNPJ, o ``NIF`` (número fiscal no país do tomador, 1–40 posições)
    ou o ``cNaoNIF`` (o motivo de não informar: 0 não informado, 1 dispensado, 2 não exigido).
    O endereço vira ``end/endExt`` (país ISO, código postal, cidade, estado/província/região),
    seguido de logradouro, número, complemento e bairro — o mesmo ``TCEndereco`` do nacional.
  • ``serv/comExt``: modo de prestação, vínculo, moeda (código BACEN) e o valor nela, os
    mecanismos de fomento, a movimentação temporária de bens e o envio ao MDIC.
  • ``tribMun``: a EXPORTAÇÃO de serviço é ``tribISSQN=3`` com o país onde o resultado se
    verifica em ``cPaisResult`` (logo depois do ``tribISSQN``).

O desenho segue a DPS que o Emissor Web monta e o SEFIN autorizou (docs §22). Aqui só se lê e se
confere; a ordem dos elementos é do ``dps.py``.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from . import documentos

#: cNaoNIF (TSCodNaoNIF): por que o NIF do tomador do exterior não vai. O 0 ("não informado na
#: nota de origem") é só do compartilhamento município → ADN: na SEFIN Nacional é E0226.
MOTIVOS_SEM_NIF = {"1": "dispensado do NIF", "2": "não exigência do NIF"}

#: Os campos do ``comExt`` com o valor padrão: o das notas de exportação de serviço que o Emissor
#: Web emitiu (sem vínculo, nenhum mecanismo de fomento, sem movimentação de bens, sem MDIC).
#: Modo, moeda e valor na moeda NÃO têm padrão: são da nota.
PADRAO_COMEXT = {"vinculo": "0", "mec_prestador": "01", "mec_tomador": "01",
                 "mov_temp_bens": "1", "mdic": "0"}

_PAIS = re.compile(r"[A-Z]{2}")
_MOEDA = re.compile(r"[0-9]{3}")


def _txt(d: dict[str, Any], *chaves: str) -> str:
    for c in chaves:
        v = d.get(c)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def tomador_do_exterior(tomador: dict[str, Any] | None) -> bool:
    """O tomador se identifica pelo NIF (ou pelo motivo de não ter um) e não por CPF/CNPJ."""
    tom = tomador or {}
    return bool(_txt(tom, "nif", "NIF") or _txt(tom, "motivo_sem_nif", "cNaoNIF"))


def nif(tomador: dict[str, Any] | None) -> str:
    """O NIF como vai na DPS: aparado, sem mexer no conteúdo (cada país tem o seu formato)."""
    return _txt(tomador or {}, "nif", "NIF")


def motivo_sem_nif(tomador: dict[str, Any] | None) -> str:
    return _txt(tomador or {}, "motivo_sem_nif", "cNaoNIF")


def identificacao(tomador: dict[str, Any] | None) -> str:
    """A identificação do tomador do exterior como a DPS a escreve: ``"NIF:<nif>"``, ``""`` para o
    ``cNaoNIF``. É o que ``emissor.mesma_nota`` compara com o ``<NIF>`` da nota achada."""
    n = nif(tomador)
    return f"NIF:{n}" if n else ""


def endereco_exterior(end: Any) -> tuple[dict[str, str], list[str]]:
    """Normaliza o endereço no exterior e diz o que falta (só os NOMES, nunca o valor).

    → (campos, faltando). ``campos``: cPais, cEndPost, xCidade, xEstProvReg, xLgr, nro ('S/N'
    vazio), xCpl ('' se ausente), xBairro. O ``xBairro`` é obrigatório no esquema mesmo fora do
    Brasil: sem bairro, repita o logradouro (o que o ISSNET faz) ou ponha o distrito."""
    if not isinstance(end, dict) or not end:
        return {}, ["endereço"]
    campos = {
        "cPais": _txt(end, "pais", "cPais").upper(),
        "cEndPost": _txt(end, "codigo_postal", "cEndPost", "cep"),
        "xCidade": _txt(end, "cidade", "xCidade"),
        "xEstProvReg": _txt(end, "estado", "provincia", "regiao", "xEstProvReg"),
        "xLgr": _txt(end, "logradouro", "xLgr"),
        "nro": _txt(end, "numero", "nro") or "S/N",
        "xCpl": _txt(end, "complemento", "xCpl"),
        "xBairro": _txt(end, "bairro", "xBairro"),
    }
    faltando = [
        nome for nome, ok in (
            ("país (ISO de 2 letras, fora do BR)",
             bool(_PAIS.fullmatch(campos["cPais"])) and campos["cPais"] != "BR"),
            ("código postal (até 11)", 0 < len(campos["cEndPost"]) <= 11),
            ("cidade", bool(campos["xCidade"])),
            ("estado/província/região", bool(campos["xEstProvReg"])),
            ("logradouro", bool(campos["xLgr"])),
            ("bairro", bool(campos["xBairro"])),
        ) if not ok
    ]
    return campos, faltando


def pais_do_tomador(tomador: dict[str, Any] | None) -> str:
    end = (tomador or {}).get("endereco") or (tomador or {}).get("end") or {}
    return _txt(end, "pais", "cPais").upper() if isinstance(end, dict) else ""


def exportacao(comercio_exterior: dict[str, Any] | None,
               tributos: dict[str, Any] | None = None) -> bool:
    """A nota é exportação de serviço: ``exportacao=True`` no comércio exterior da nota ou
    ``tribISSQN=3`` nos tributos da config — as duas portas dão a mesma DPS."""
    return (bool((comercio_exterior or {}).get("exportacao"))
            or str((tributos or {}).get("tribISSQN", "1")).strip() == "3")


def pais_resultado(comercio_exterior: dict[str, Any] | None,
                   tomador: dict[str, Any] | None) -> str:
    """O país onde o resultado da exportação se verifica (``cPaisResult``): o declarado na nota
    ou, sem ele, o do endereço do tomador."""
    return (_txt(comercio_exterior or {}, "pais_resultado", "cPaisResult").upper()
            or pais_do_tomador(tomador))


def comext(comercio_exterior: dict[str, Any]) -> dict[str, str]:
    """Os campos do ``comExt`` na ordem do XSD (TCComExterior), já com os padrões."""
    ce = {**PADRAO_COMEXT, **{k: v for k, v in comercio_exterior.items() if v is not None}}
    campos = {
        "mdPrestacao": _txt(ce, "modo_prestacao", "mdPrestacao"),
        "vincPrest": _txt(ce, "vinculo", "vincPrest"),
        "tpMoeda": _txt(ce, "moeda", "tpMoeda"),
        "vServMoeda": _txt(ce, "valor_moeda", "vServMoeda"),
        "mecAFComexP": _txt(ce, "mec_prestador", "mecAFComexP").zfill(2),
        "mecAFComexT": _txt(ce, "mec_tomador", "mecAFComexT").zfill(2),
        "movTempBens": _txt(ce, "mov_temp_bens", "movTempBens"),
        "nDI": _txt(ce, "numero_di", "nDI"),
        "nRE": _txt(ce, "numero_re", "nRE"),
        "mdic": _txt(ce, "mdic"),
    }
    if campos["vServMoeda"]:
        campos["vServMoeda"] = _dec2(campos["vServMoeda"]) or campos["vServMoeda"]
    return campos


def _dec2(valor: str) -> str:
    texto = valor.replace("R$", "").strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        d = Decimal(texto)
    except InvalidOperation:
        return ""
    if not d.is_finite() or d <= 0:
        return ""
    return str(d.quantize(Decimal("0.01")))


def validar_tomador_exterior(tomador: dict[str, Any] | None) -> list[str]:
    """O tomador do exterior: identificação, nome e endereço. Vazio = nada a dizer."""
    if not tomador_do_exterior(tomador):
        return []
    tom = tomador or {}
    problemas: list[str] = []
    if documentos.norm_documento(tom.get("cpf_cnpj") or tom.get("cpf") or tom.get("cnpj")):
        problemas.append("tomador com CPF/CNPJ E com NIF/motivo sem NIF: a DPS leva um só "
                         "(CPF/CNPJ é tomador do Brasil; NIF é do exterior)")
    n, motivo = nif(tom), motivo_sem_nif(tom)
    if n and motivo:
        problemas.append("tomador do exterior com NIF E motivo_sem_nif: informe um dos dois")
    if n and len(n) > 40:
        problemas.append("NIF do tomador do exterior tem até 40 posições")
    if motivo and motivo not in MOTIVOS_SEM_NIF:
        problemas.append("E0226: motivo_sem_nif deve ser 1 (dispensado) ou 2 (não exigido); "
                         f"recebido {motivo!r} (o 0 a SEFIN Nacional recusa)")
    if not _txt(tom, "nome", "xNome"):
        problemas.append("E0233: tomador do exterior EXIGE nome (xNome)")
    # E0242: NIF (e, na NT 009, também o cNaoNIF) exige o endereço no exterior — exigido sempre
    # aqui, que é o que vale nos dois leiautes.
    _, faltando = endereco_exterior(tom.get("endereco") or tom.get("end"))
    if faltando:
        problemas.append("E0242: tomador do exterior exige o endereço no exterior; falta "
                         + ", ".join(faltando))
    return problemas


def validar_comercio_exterior(comercio_exterior: dict[str, Any] | None,
                              tomador: dict[str, Any] | None,
                              tributos: dict[str, Any] | None = None,
                              cnbs: str | None = None) -> list[str]:
    """O grupo ``comExt`` e a exportação (``tribISSQN=3``) desta nota (Anexo I v1.01, §22).
    ``cnbs``: o Item da NBS da config — obrigatório com tomador do exterior (E0318)."""
    tributos = tributos or {}
    problemas: list[str] = []
    fora = tomador_do_exterior(tomador)
    if fora and not documentos.digitos(cnbs):
        problemas.append("E0318: tomador do exterior exige o Item da NBS (servico.cNBS)")
    if not comercio_exterior:
        if fora or exportacao(None, tributos):
            problemas.append("E0330: tomador do exterior ou exportação (tribISSQN=3) exige o "
                             "comercio_exterior da nota (modo de prestação, moeda e valor nela)")
        return problemas
    c = comext(comercio_exterior)
    if c["mdPrestacao"] not in {"1", "2", "3", "4"}:
        problemas.append("E0333: comercio_exterior.modo_prestacao deve ser 1 Transfronteiriço, "
                         "2 Consumo no Brasil, 3 Movimento temporário de PF ou 4 Consumo no "
                         f"Exterior; recebido {c['mdPrestacao']!r}")
    if c["vincPrest"] not in {"0", "1", "2", "3", "4", "5", "6", "9"}:
        problemas.append(f"comercio_exterior.vinculo inválido: {c['vincPrest']!r}")
    if not _MOEDA.fullmatch(c["tpMoeda"]):
        problemas.append("comercio_exterior.moeda é o código BACEN de 3 dígitos (220 = dólar "
                         f"dos EUA, 978 = euro); recebido {c['tpMoeda']!r}")
    if not _dec2(_txt(comercio_exterior, "valor_moeda", "vServMoeda")):
        problemas.append("comercio_exterior.valor_moeda (o valor na moeda estrangeira) é "
                         "obrigatório e maior que zero")
    for campo, nome, ecod in (("mecAFComexP", "mec_prestador", "E0341"),
                              ("mecAFComexT", "mec_tomador", "E0343")):
        if not re.fullmatch(r"[0-9]{2}", c[campo]) or c[campo] == "00":
            problemas.append(f"{ecod}: comercio_exterior.{nome} são 2 dígitos, 01 = nenhum (o 00 "
                             f"a SEFIN recusa); recebido {c[campo]!r}")
    mov = c["movTempBens"]
    if mov not in {"1", "2", "3"}:
        problemas.append("E0345: comercio_exterior.mov_temp_bens deve ser 1 (não), 2 (DI) ou 3 "
                         f"(RE); recebido {mov!r}")
    elif mov == "1" and (c["nDI"] or c["nRE"]):
        problemas.append("E0354: mov_temp_bens=1 não leva numero_di nem numero_re")
    elif mov == "2" and not c["nDI"]:
        problemas.append("E0352: mov_temp_bens=2 exige numero_di")
    elif mov == "3" and not c["nRE"]:
        problemas.append("E0356: mov_temp_bens=3 exige numero_re")
    if c["mdic"] not in {"0", "1"}:
        problemas.append(f"comercio_exterior.mdic deve ser 0 ou 1; recebido {c['mdic']!r}")
    if exportacao(comercio_exterior, tributos):
        # E0590: com a prestação no Brasil, a exportação leva o país do resultado. O tomador do
        # Brasil também pode exportar (cenários 2 e 30 do Anexo I) — aí o país vem declarado.
        pais = pais_resultado(comercio_exterior, tomador)
        if not _PAIS.fullmatch(pais) or pais == "BR":
            problemas.append("E0590: exportação (tribISSQN=3) exige o país onde o resultado se "
                             "verifica (pais_resultado, ISO de 2 letras, fora do BR), ou o "
                             "endereço do tomador no exterior")
        if str(tributos.get("tpRetISSQN", "1")).strip() != "1":
            problemas.append("exportação de serviço não tem ISS retido (tpRetISSQN deve ser 1)")
    return problemas

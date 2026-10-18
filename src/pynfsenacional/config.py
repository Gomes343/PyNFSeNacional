"""Configuração do cliente/prestador — carrega o JSON descrito em
docs/conhecimento-fiscal.md §3 em dataclasses tipadas.

Duas responsabilidades:
  • **Carregar/representar** o JSON em dataclasses (`from_dict`/`from_json`), com erro
    de schema amigável (`ConfigError`) em vez de `TypeError` cru.
  • **Validar fiscalmente** (`validar`) — os E-codes que dão para pegar ANTES de tocar o
    SEFIN (cTribNac 6 díg, pTotTribSN se Simples, CNPJ/CPF mód-11…). O cTribMun é OPCIONAL
    (alguns municípios não usam desdobro — ex.: Curitiba rejeita o campo com E0315).
A montagem do XML da DPS fica em dps.py.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from . import documentos

_AMBIENTES = ("homologacao", "producao")

# totTrib/pTotTrib (§14): as três parcelas do percentual aproximado, na ordem do XSD, e o E-code
# de cada uma quando sai do intervalo 0–100%.
PTOTTRIB_CHAVES = ("pTotTribFed", "pTotTribEst", "pTotTribMun")
_PTOTTRIB_ECODE = {"pTotTribFed": "E0706", "pTotTribEst": "E0707", "pTotTribMun": "E0708"}
# servico.ibscbs (§8/§14): o que este montador sabe emitir. Chave fora daqui é recusada pelo
# validar() — emitir o grupo sem o que a config pediu seria nota em desconformidade, calada.
IBSCBS_CHAVES = ("finNFSe", "indFinal", "cIndOp", "indDest", "CST", "cClassTrib")
# CST do PIS/COFINS que dispensam o tipo de retenção (E0698): Nenhum, sem incidência, suspensão.
_CST_SEM_TPRET = ("00", "08", "09")


def percentual(valor: Any) -> Decimal | None:
    """'11.33' / '11,33' / 3 / 0 → Decimal; vazio ou não numérico → None."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return Decimal(str(valor).strip().replace(",", "."))
    except InvalidOperation:
        return None


class ConfigError(ValueError):
    """Config malformada (bloco ausente, campo desconhecido, tipo errado)."""


def _construir(tipo: type, dados: dict[str, Any], contexto: str,
               ignorar: tuple[str, ...] = ()) -> Any:
    """Constrói uma dataclass a partir de um dict, com erro de schema amigável.

    Campos em `ignorar` são descartados (ex.: endereço/nome do prestador, que não
    são enviados — E0128/E0121). Chave desconhecida ou faltando → `ConfigError` com
    contexto, em vez do `TypeError` cru do `**splat`.
    """
    if not isinstance(dados, dict):
        raise ConfigError(f"{contexto}: esperado objeto JSON, recebido {type(dados).__name__}")
    dados = {k: v for k, v in dados.items() if k not in ignorar}
    campos = {f.name for f in dataclasses.fields(tipo)}
    desconhecidos = set(dados) - campos
    if desconhecidos:
        raise ConfigError(
            f"{contexto}: campo(s) não reconhecido(s): {sorted(desconhecidos)}. "
            f"Válidos: {sorted(campos)}"
        )
    try:
        return tipo(**dados)
    except TypeError as e:  # campo obrigatório ausente
        raise ConfigError(f"{contexto}: {e}") from e


@dataclass
class Certificado:
    """Certificado A1 ICP-Brasil do PRÓPRIO prestador (.pfx). NUNCA versionar."""
    path: str
    senha: str


@dataclass
class Regime:
    """Regime tributário do prestador (ver §3)."""
    opSimpNac: int          # 1=Não Optante · 2=MEI · 3=Optante ME/EPP (Simples)
    regApTribSN: int = 1    # apuração do SN (se optante)
    regEspTrib: int = 0     # regime especial (0=Nenhum)


@dataclass
class Prestador:
    cnpj: str               # 14 dígitos
    codigo_municipio: str   # IBGE 7 díg do emitente
    regime: Regime
    uf: str | None = None
    inscricao_municipal: str | None = None
    # A IM é OPCIONAL e quem decide se ela vai na DPS é o CNC (Cadastro Nacional de
    # Contribuintes) do município — POR CNPJ, não por cidade (§10). Tem no CNC → mandar
    # (senão E0116); não tem → deixar VAZIO/None (mandar dá E0120). Nunca preencher de
    # enfeite ("0000"): ou é recusado, ou passa e vira nota real com dado falso.
    # Nome/endereço do prestador NÃO são enviados quando ele é o emitente (E0128/E0121).


@dataclass
class Servico:
    codigo_municipio_prestacao: str   # IBGE do local da prestação
    cTribNac: str                     # 6 dígitos (LC116)
    cTribMun: str = ""                # desdobro municipal — OPCIONAL (minOccurs=0 no XSD)
    # A maioria administra o par cTribNac+cTribMun (RJ, Ubatuba), mas alguns NÃO usam desdobro e
    # REJEITAM o campo: Curitiba devolve E0315 ("não é permitido informar 000"). Nesses casos,
    # deixar VAZIO — o dps.py omite o elemento (as notas reais de Curitiba não têm cTribMun).
    descricao_padrao: str = "Serviço Prestado"
    # tributos aceitos: "pTotTribSN" (% do Simples, ME/EPP) · "indTotTrib" (MEI/Não Optante)
    # · "tribISSQN" · "tpRetISSQN" · "piscofins_cst" (CST do PIS/COFINS; default "08" =
    # Operação sem Incidência. Alguns contribuintes emitem "00" = Nenhum — o critério é o XML
    # que o próprio contribuinte já emitiu; ver §12).
    tributos: dict[str, Any] = field(default_factory=dict)  # ex.: {"pTotTribSN": "6.00"}
    # Texto livre do <infoCompl><xInfComp> (serv/infoCompl/xInfComp, 0-1, até 2000 chars).
    # NÃO é obrigatório e NÃO tem efeito fiscal: é um recado impresso no DANFSe ("Inf. Cont.:").
    # Uso típico: o prestador do Simples avisar o tomador PJ de que não há retenção de IRRF
    # (IN RFB 765/2007, art. 1º). Vazio = elemento omitido.
    info_complementares: str = ""
    # Item da NBS (serv/cServ/cNBS, 9 dígitos), depois do xDescServ. Opcional no XSD que o SEFIN
    # aplica; o portal o exige do Regime Regular e ele classifica o serviço para o IBS/CBS (§14).
    # Vazio = elemento omitido (a DPS do Simples sai como sempre saiu).
    cNBS: str = ""
    # Grupo IBSCBS da DPS (§8/§14) — só a CLASSIFICAÇÃO; os valores o SEFIN calcula. Chaves:
    # cIndOp, CST, cClassTrib (obrigatórias no bloco), indFinal (opcional), finNFSe e indDest
    # (só "0"). Vazio = grupo omitido — o Simples dispensa o grupo até 31/12/2026.
    ibscbs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClienteConfig:
    id: str
    nome_cliente: str
    certificado: Certificado
    prestador: Prestador
    servico: Servico
    ambiente: str = "homologacao"
    dados_nota: dict[str, Any] = field(default_factory=dict)

    # ── carregamento ──────────────────────────────────────────────────────────
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ClienteConfig:
        if not isinstance(d, dict):
            raise ConfigError(f"config: esperado objeto JSON, recebido {type(d).__name__}")
        for chave in ("id", "nome_cliente", "certificado", "prestador", "servico"):
            if chave not in d:
                raise ConfigError(f"config: bloco/campo obrigatório ausente: '{chave}'")

        cert = _construir(Certificado, d["certificado"], "certificado")
        prest_raw = dict(d["prestador"])
        if "regime" not in prest_raw:
            raise ConfigError("prestador: bloco 'regime' obrigatório ausente")
        regime = _construir(Regime, prest_raw.pop("regime"), "prestador.regime")
        # endereço/telefone/email do prestador NÃO vão na DPS (E0128/E0121): descartados.
        prestador = _construir(
            Prestador, {**prest_raw, "regime": regime}, "prestador",
            ignorar=("endereco", "telefone", "email"),
        )
        servico = _construir(Servico, d["servico"], "servico")
        return cls(
            id=str(d["id"]),
            nome_cliente=d["nome_cliente"],
            certificado=cert,
            prestador=prestador,
            servico=servico,
            ambiente=d.get("ambiente", "homologacao"),
            dados_nota=d.get("dados_nota", {}),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> ClienteConfig:
        raw = Path(path).read_text(encoding="utf-8")
        try:
            dados = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ConfigError(
                f"{path}: JSON inválido ({e}). O config real é JSON puro — comentários "
                f"// só existem no exemplo anotado .jsonc, não num config carregável."
            ) from e
        return cls.from_dict(dados)

    # ── validação fiscal ──────────────────────────────────────────────────────
    def validar(self) -> list[str]:
        """Lista os problemas fiscais (vazia = ok). Pega, ANTES do SEFIN, os E-codes
        que são determinísticos a partir da config. Ver docs/conhecimento-fiscal.md §4.
        """
        problemas: list[str] = []
        p, s, r = self.prestador, self.servico, self.prestador.regime

        # Prestador (emitente)
        if not documentos.cnpj_valido(p.cnpj):
            problemas.append(
                f"CNPJ do prestador inválido (14 dígitos + dígito verificador): {p.cnpj!r}"
            )
        if not (p.codigo_municipio.isdigit() and len(p.codigo_municipio) == 7):
            problemas.append(
                f"código IBGE do município do prestador deve ter 7 dígitos: {p.codigo_municipio!r}"
            )
        # IM "de enfeite" (só zeros / sem dígito) é PIOR que omitir: ou o SEFIN recusa, ou passa
        # e vira nota fiscal real com dado falso. Quem decide se a IM vai na DPS é o CNC do
        # município, POR CNPJ (E0116 × E0120) — sem IM no CNC, deixar vazio/None (§10).
        im = (p.inscricao_municipal or "").strip()
        if im and not documentos.digitos(im).strip("0"):
            problemas.append(
                f"prestador.inscricao_municipal sem dígito significativo: {im!r}. A IM é "
                f"OPCIONAL — se o CNC do município não tem IM para este CNPJ, deixe vazio/null "
                f"(informar dá E0120); nunca preencha de enfeite"
            )
        if r.opSimpNac not in (1, 2, 3):
            problemas.append(
                f"regime.opSimpNac deve ser 1 (Não Optante), 2 (MEI) ou 3 (ME/EPP); "
                f"recebido {r.opSimpNac!r}"
            )

        # Serviço / códigos de tributação
        if not (s.cTribNac.isdigit() and len(s.cTribNac) == 6):
            problemas.append(
                f"E1235: cTribNac deve ter exatamente 6 dígitos (TSCodTribNac); "
                f"recebido {s.cTribNac!r}"
            )
        # cTribMun é OPCIONAL (minOccurs=0 no XSD). NÃO validamos presença: a maioria dos
        # municípios administra a combinação cTribNac+cTribMun (e o SEFIN devolve E0312 quando falta
        # onde é exigido — a autoridade é o SEFIN), mas há municípios que NÃO usam desdobro e
        # REJEITAM o campo (Curitiba: E0315 "não é permitido informar 000"). Nesses, deixa-se
        # vazio e o dps.py omite o elemento. Faltar onde o município exige vira E0312 no envio.
        if not (s.codigo_municipio_prestacao.isdigit()
                and len(s.codigo_municipio_prestacao) == 7):
            problemas.append(
                f"código IBGE do local da prestação deve ter 7 dígitos: "
                f"{s.codigo_municipio_prestacao!r}"
            )

        # Tributos (E0712/E1235): só ME/EPP optante do Simples (opSimpNac=3) exige pTotTribSN.
        # MEI (opSimpNac=2) é ISENTO de declarar o valor aproximado dos tributos (Decreto
        # 8.264/2014) → usa totTrib/indTotTrib=0, NÃO pTotTribSN. Não Optante (1) usa indTotTrib.
        if r.opSimpNac == 3:
            ptot = s.tributos.get("pTotTribSN")
            if ptot is None or str(ptot).strip() == "":
                problemas.append(
                    "E0712/E1235: prestador é ME/EPP optante do Simples (opSimpNac=3) → "
                    "'pTotTribSN' é obrigatório em servico.tributos"
                )
            else:
                try:
                    float(str(ptot).replace(",", "."))
                except ValueError:
                    problemas.append(f"servico.tributos.pTotTribSN não é numérico: {ptot!r}")

        problemas += self._validar_regime_regular()

        # Ambiente
        if self.ambiente not in _AMBIENTES:
            problemas.append(
                f"ambiente inválido: {self.ambiente!r} (use 'homologacao' ou 'producao')"
            )
        return problemas

    def _validar_regime_regular(self) -> list[str]:
        """O que entrou com o Regime Regular e a retenção (§12, §14, §15): Item da NBS, tipo de
        retenção do ISSQN e do PIS/COFINS, pTotTrib e o grupo IBS/CBS. Tudo opcional — config
        sem nenhum desses campos não ganha problema novo (Simples e MEI ficam como estavam)."""
        problemas: list[str] = []
        s, r, t = self.servico, self.prestador.regime, self.servico.tributos

        nbs = (s.cNBS or "").strip()
        if nbs and len(documentos.digitos(nbs)) != 9:
            problemas.append(
                f"servico.cNBS deve ter 9 dígitos (Item da NBS, TSCodNBS); recebido {nbs!r}"
            )

        # Retenção do ISSQN (§15). 3 = pelo intermediário, que exige o grupo <interm>.
        ret = str(t.get("tpRetISSQN", 1)).strip()
        if ret not in ("1", "2", "3"):
            problemas.append(
                f"servico.tributos.tpRetISSQN deve ser 1 (não retido), 2 (retido pelo tomador) "
                f"ou 3 (retido pelo intermediário); recebido {t.get('tpRetISSQN')!r}"
            )
        elif ret == "3":
            problemas.append(
                "tpRetISSQN=3 (retido pelo intermediário) exige o grupo do intermediário "
                "(<interm>), que esta biblioteca ainda não emite"
            )
        elif ret == "2":
            if r.opSimpNac == 2:
                problemas.append("E0583: MEI não sofre retenção do ISSQN — use tpRetISSQN=1")
            if r.regEspTrib != 0:
                problemas.append(
                    "E0588: prestador com regime especial de tributação (regEspTrib≠0) não "
                    "sofre retenção do ISSQN — use tpRetISSQN=1"
                )
            if str(t.get("tribISSQN", 1)).strip() in ("2", "3", "4"):
                problemas.append(
                    "E0580: serviço imune, exportado ou sem incidência (tribISSQN 2/3/4) não "
                    "tem retenção do ISSQN — use tpRetISSQN=1"
                )
            if r.opSimpNac == 3 and r.regApTribSN == 1:
                problemas.append(
                    "E0621: ME/EPP com o ISS pelo Simples e ISS RETIDO exige a alíquota (pAliq) "
                    "na DPS, que esta biblioteca ainda não emite (§15)"
                )

        # tribFed/piscofins (§12) — o MEI não emite tribFed (E0676), então não se aplica.
        if r.opSimpNac != 2:
            tprp = t.get("tpRetPisCofins")
            if tprp is not None and not (str(tprp).strip().isdigit()
                                         and len(str(tprp).strip()) == 1):
                problemas.append(
                    f"servico.tributos.tpRetPisCofins deve ser um dígito de 0 a 9 (NT 007); "
                    f"recebido {tprp!r}"
                )
            cst = str(t.get("piscofins_cst", "08")).strip()
            if cst not in _CST_SEM_TPRET and tprp is None:
                problemas.append(
                    f"E0698: CST do PIS/COFINS {cst!r} (diferente de 00, 08 e 09) exige "
                    f"servico.tributos.tpRetPisCofins"
                )

        # totTrib/pTotTrib (§14) — o percentual aproximado em três parcelas, só Não Optante.
        ptt = t.get("pTotTrib")
        if ptt is not None:
            if r.opSimpNac != 1:
                problemas.append(
                    "servico.tributos.pTotTrib é para o Não Optante (opSimpNac=1): o ME/EPP usa "
                    "pTotTribSN e o MEI é isento (Decreto 8.264/2014) — §3/§14"
                )
            elif not isinstance(ptt, dict) or set(ptt) != set(PTOTTRIB_CHAVES):
                recebidas = sorted(ptt) if isinstance(ptt, dict) else type(ptt).__name__
                problemas.append(
                    f"servico.tributos.pTotTrib deve ter exatamente {', '.join(PTOTTRIB_CHAVES)}; "
                    f"recebido {recebidas}"
                )
            else:
                for k in PTOTTRIB_CHAVES:
                    v = percentual(ptt[k])
                    if v is None or not (0 <= v <= 100):
                        problemas.append(
                            f"{_PTOTTRIB_ECODE[k]}: pTotTrib.{k} deve ser um percentual de 0 a "
                            f"100; recebido {ptt[k]!r}"
                        )

        # Grupo IBS/CBS (§8/§14).
        ibs = s.ibscbs
        if not isinstance(ibs, dict):
            problemas.append(f"servico.ibscbs deve ser um objeto; recebido {type(ibs).__name__}")
        elif ibs:
            desconhecidas = sorted(set(ibs) - set(IBSCBS_CHAVES))
            if desconhecidas:
                problemas.append(
                    f"servico.ibscbs: {desconhecidas} não é coberto por esta biblioteca "
                    f"(cobertos: {', '.join(IBSCBS_CHAVES)}) — §8"
                )
            for k, n in (("cIndOp", 6), ("CST", 3), ("cClassTrib", 6)):
                cod = str(ibs.get(k) or "").strip()
                if not (cod.isdigit() and len(cod) == n):
                    problemas.append(
                        f"servico.ibscbs.{k} é obrigatório no grupo IBS/CBS, com {n} dígitos; "
                        f"recebido {ibs.get(k)!r}"
                    )
            if str(ibs.get("finNFSe", "0")).strip() != "0":
                problemas.append(
                    f"servico.ibscbs.finNFSe: o leiaute só tem 0 (NFS-e regular); "
                    f"recebido {ibs.get('finNFSe')!r}"
                )
            if "indFinal" in ibs and str(ibs["indFinal"]).strip() not in ("0", "1"):
                problemas.append(
                    f"servico.ibscbs.indFinal deve ser 0 ou 1; recebido {ibs['indFinal']!r}"
                )
            if str(ibs.get("indDest", "0")).strip() != "0":
                problemas.append(
                    "servico.ibscbs.indDest=1 (destinatário diferente do adquirente) exige o "
                    "grupo <dest>, que esta biblioteca ainda não emite — §8"
                )
        return problemas


def validar_tomador(tomador: dict[str, Any] | None) -> list[str]:
    """Valida o bloco do tomador da emissão (E1235 §7). Tomador `None`/sem doc =
    consumidor final (omite <toma>) → sem problemas. Com documento, EXIGE nome e
    documento válido (mód-11)."""
    if not tomador:
        return []
    # CNPJ alfanumérico do tomador: preserva letras (CPF, só dígitos, sai igual).
    doc = documentos.norm_documento(
        tomador.get("cpf_cnpj") or tomador.get("cpf") or tomador.get("cnpj")
    )
    if not doc:
        return []  # sem documento → tratado como não identificado (omite <toma>)

    problemas: list[str] = []
    nome = (tomador.get("nome") or tomador.get("xNome") or "").strip()
    if not nome:
        problemas.append(
            "E1235: tomador identificado EXIGE nome (xNome) — a API não resolve pela "
            "Receita (§7); informe o nome ou resolva por CNPJ (BrasilAPI)"
        )
    if len(doc) == 14:
        if not documentos.cnpj_valido(doc):
            problemas.append(f"CNPJ do tomador inválido: {doc!r}")
    elif len(doc) == 11:
        if not documentos.cpf_valido(doc):
            problemas.append(f"CPF do tomador inválido: {doc!r}")
    else:
        problemas.append(
            f"documento do tomador deve ser CPF (11) ou CNPJ (14 dígitos); recebido {doc!r}"
        )
    return problemas


def validar_retencao(cfg: ClienteConfig, tomador: dict[str, Any] | None) -> list[str]:
    """ISS retido pelo tomador (`tributos.tpRetISSQN=2`) × o tomador DESTA nota (§15).

    A retenção transforma dois opcionais em obrigatórios: o tomador identificado (**E0204**) e o
    endereço nacional dele **completo** (**E0237**). O `<end>` é bloco atômico (§7) — incompleto,
    o montador o omite e a nota seria rejeitada; aqui a recusa sai antes, dizendo QUAIS campos
    faltam (nunca os valores). Sem retenção, nada é exigido."""
    if str(cfg.servico.tributos.get("tpRetISSQN", 1)).strip() != "2":
        return []
    tom = tomador or {}
    doc = documentos.norm_documento(tom.get("cpf_cnpj") or tom.get("cpf") or tom.get("cnpj"))
    if not doc:
        return ["E0204: ISS retido pelo tomador (tpRetISSQN=2) exige o tomador identificado "
                "por CPF/CNPJ"]
    _, faltando = documentos.endereco_nacional(tom.get("endereco") or tom.get("end"))
    if faltando:
        return [f"E0237: ISS retido pelo tomador (tpRetISSQN=2) exige o endereço nacional "
                f"completo do tomador — falta(m): {', '.join(faltando)}"]
    return []

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
from pathlib import Path
from typing import Any

from . import documentos

_AMBIENTES = ("homologacao", "producao")


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

        # Ambiente
        if self.ambiente not in _AMBIENTES:
            problemas.append(
                f"ambiente inválido: {self.ambiente!r} (use 'homologacao' ou 'producao')"
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

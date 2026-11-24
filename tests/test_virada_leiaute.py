"""A virada de leiaute (§19): o SEFIN troca de pacote do XSD antes da lib.

A produção aplica o pacote de 09/02/2026 e deve passar ao da NT 009 em 01/12/2026. No dia em que
virar, toda DPS no leiaute antigo volta E1235 citando o `finNFSe`. A lib manda a MESMA DPS de
novo no outro leiaute (recusa de esquema não cria nota) e guarda o que passou no `out_dir`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from lxml import etree

from pynfsenacional import ClienteConfig, Emissor
from pynfsenacional.config import (
    LEIAUTE_NT009,
    LEIAUTE_PRODUCAO,
    leiaute_recusado,
    outro_leiaute,
)
from pynfsenacional.sefin import RespostaSefin

TOMADOR = {"cpf_cnpj": "11144477735", "nome": "Fulano de Tal"}
# As duas mensagens medidas em homologação (31/10/2026), uma para cada sentido.
MSG_ANTIGO_NO_NOVO = ("[E1235] Falha no esquema XML: The element 'infDPS' has invalid child "
                      "element 'cLocEmi'. List of possible elements expected: "
                      "'cMotivoEmisTI, finNFSe'.")
MSG_NOVO_NO_ANTIGO = "[E1235] Falha no esquema XML: invalid child element 'finNFSe'"


class SefinDeUmLeiaute:
    """SEFIN que aplica UM pacote: a DPS com `finNFSe` no `infDPS` é da NT 009."""

    def __init__(self, aplica: str, *, depois: RespostaSefin | None = None):
        self.aplica = aplica
        self.depois = depois or RespostaSefin(ok=True, chave_acesso="33OK", numero_nfse="9",
                                              nfse_xml="<NFSe/>")
        self.enviados: list[tuple[str, str]] = []      # (leiaute da DPS, Id)

    def verificar_dps(self, idd):
        return False

    def emitir(self, xml):
        raiz = etree.fromstring(xml.encode())
        inf = raiz.find("{*}infDPS")
        nt009 = inf.find("{*}finNFSe") is not None
        leiaute = LEIAUTE_NT009 if nt009 else LEIAUTE_PRODUCAO
        self.enviados.append((leiaute, inf.get("Id")))
        if leiaute != self.aplica:
            msg = MSG_NOVO_NO_ANTIGO if nt009 else MSG_ANTIGO_NO_NOVO
            return RespostaSefin(ok=False, erro_codigo="E1235", erro_msg=msg.split("] ", 1)[1])
        return self.depois


@pytest.fixture
def config(config_dict, pfx_teste):
    caminho, senha = pfx_teste
    config_dict["certificado"] = {"path": str(caminho), "senha": senha}
    return ClienteConfig.from_dict(config_dict)


def _emitir(emissor, monkeypatch, fake):
    monkeypatch.setattr(emissor, "_sefin_client", lambda: fake)
    return emissor.emitir(valor=Decimal("150.00"), descricao="Servico de teste",
                          tomador=TOMADOR)


def test_reconhece_as_duas_mensagens_medidas():
    assert leiaute_recusado("E1235", MSG_ANTIGO_NO_NOVO)
    assert leiaute_recusado("E1235", MSG_NOVO_NO_ANTIGO)
    assert not leiaute_recusado("E1235", "toma incompleto (expected CAEPF, IM, xNome)")
    assert not leiaute_recusado("E0322", "finNFSe")          # outro código não é esquema
    assert not leiaute_recusado("E1235", None)
    assert outro_leiaute(LEIAUTE_PRODUCAO) == LEIAUTE_NT009
    assert outro_leiaute(LEIAUTE_NT009) == LEIAUTE_PRODUCAO


def test_producao_virou_a_nota_sai_no_novo_e_o_proximo_ja_vai_direto(config, tmp_path,
                                                                      monkeypatch):
    fake = SefinDeUmLeiaute(LEIAUTE_NT009)
    nota = _emitir(Emissor(config, ambiente="producao", out_dir=tmp_path), monkeypatch, fake)
    assert nota.emitida and nota.erro_msg is None
    # a MESMA DPS (mesmo Id) foi duas vezes: antigo, recusado; novo, aceito
    assert [lei for lei, _ in fake.enviados] == [LEIAUTE_PRODUCAO, LEIAUTE_NT009]
    assert fake.enviados[0][1] == fake.enviados[1][1]
    assert (tmp_path / "leiaute_producao.txt").read_text() == LEIAUTE_NT009

    # outra emissão (outro processo, mesmo out_dir): já sai no novo, sem a recusa
    fake2 = SefinDeUmLeiaute(LEIAUTE_NT009)
    nota2 = _emitir(Emissor(config, ambiente="producao", out_dir=tmp_path), monkeypatch, fake2)
    assert nota2.emitida
    assert [lei for lei, _ in fake2.enviados] == [LEIAUTE_NT009]


def test_producao_sem_virada_nada_muda(config, tmp_path, monkeypatch):
    fake = SefinDeUmLeiaute(LEIAUTE_PRODUCAO)
    nota = _emitir(Emissor(config, ambiente="producao", out_dir=tmp_path), monkeypatch, fake)
    assert nota.emitida
    assert [lei for lei, _ in fake.enviados] == [LEIAUTE_PRODUCAO]
    assert not (tmp_path / "leiaute_producao.txt").exists()


def test_a_virada_de_volta_tambem_e_seguida(config, tmp_path, monkeypatch):
    """Gravado NT 009 e o SEFIN voltou ao antigo (recuo do governo): volta junto."""
    (tmp_path / "leiaute_producao.txt").write_text(LEIAUTE_NT009)
    fake = SefinDeUmLeiaute(LEIAUTE_PRODUCAO)
    nota = _emitir(Emissor(config, ambiente="producao", out_dir=tmp_path), monkeypatch, fake)
    assert nota.emitida
    assert [lei for lei, _ in fake.enviados] == [LEIAUTE_NT009, LEIAUTE_PRODUCAO]
    assert (tmp_path / "leiaute_producao.txt").read_text() == LEIAUTE_PRODUCAO


def test_recusa_de_negocio_no_novo_leiaute_ainda_prova_a_virada(config, tmp_path, monkeypatch):
    """O esquema passou e uma regra recusou a nota: o leiaute é o certo, o erro é o da regra."""
    recusa = RespostaSefin(ok=False, erro_codigo="E0312", erro_msg="regra qualquer")
    fake = SefinDeUmLeiaute(LEIAUTE_NT009, depois=recusa)
    nota = _emitir(Emissor(config, ambiente="producao", out_dir=tmp_path), monkeypatch, fake)
    assert not nota.emitida and nota.erro_msg.startswith("[E0312]")
    assert (tmp_path / "leiaute_producao.txt").read_text() == LEIAUTE_NT009


def test_nenhum_dos_dois_passa_nao_grava_e_nao_insiste(config, tmp_path, monkeypatch):
    class Recusa:
        enviados = 0

        def verificar_dps(self, idd):
            return False

        def emitir(self, xml):
            Recusa.enviados += 1
            return RespostaSefin(ok=False, erro_codigo="E1235",
                                 erro_msg="invalid child element 'finNFSe'")

    nota = _emitir(Emissor(config, ambiente="producao", out_dir=tmp_path), monkeypatch,
                   Recusa())
    assert not nota.emitida and nota.erro_msg.startswith("[E1235]")
    assert Recusa.enviados == 2                                  # uma virada só, não um laço
    assert not (tmp_path / "leiaute_producao.txt").exists()


def test_leiaute_forcado_na_config_nao_vira(config_dict, pfx_teste, tmp_path, monkeypatch):
    caminho, senha = pfx_teste
    config_dict["certificado"] = {"path": str(caminho), "senha": senha}
    config_dict["leiaute"] = LEIAUTE_PRODUCAO
    fake = SefinDeUmLeiaute(LEIAUTE_NT009)
    nota = _emitir(Emissor(ClienteConfig.from_dict(config_dict), ambiente="producao",
                           out_dir=tmp_path), monkeypatch, fake)
    assert not nota.emitida
    assert [lei for lei, _ in fake.enviados] == [LEIAUTE_PRODUCAO]
    assert "Configure" in nota.erro_msg                          # a dica de antes segue valendo


def test_recusa_sem_ecode_ou_rede_nao_vira(config, tmp_path, monkeypatch):
    """Resposta que não veio (rede): pode ter virado nota — nunca reenviar no outro leiaute."""
    class SemResposta:
        enviados = 0

        def verificar_dps(self, idd):
            return False

        def emitir(self, xml):
            SemResposta.enviados += 1
            return RespostaSefin(ok=False, erro_msg="timeout")

    _emitir(Emissor(config, ambiente="producao", out_dir=tmp_path), monkeypatch, SemResposta())
    assert SemResposta.enviados == 1

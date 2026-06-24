"""Fixtures compartilhadas dos testes.

`CONFIG_VALIDA`: config fictícia mas **fiscalmente válida** (CNPJ/CPF passam no
mód-11, IBGE com 7 dígitos) — base para mutar campo a campo e provar que `validar()`
pega cada E-code. Dados fictícios: CNPJ/CPF de teste públicos; nada real.
"""

from __future__ import annotations

import copy
import datetime as _dt
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

# CNPJ 11.222.333/0001-81 e CPF 111.444.777-35 são válidos no mód-11 e de uso público p/ teste.
CONFIG_VALIDA: dict[str, Any] = {
    "id": "exemplo",
    "nome_cliente": "EMPRESA EXEMPLO LTDA",
    "ambiente": "homologacao",
    "certificado": {"path": "certs/exemplo.pfx", "senha": "0000"},
    "prestador": {
        "cnpj": "11222333000181",
        "codigo_municipio": "3304557",
        "uf": "RJ",
        "regime": {"opSimpNac": 3, "regApTribSN": 1, "regEspTrib": 0},
    },
    "servico": {
        "codigo_municipio_prestacao": "3304557",
        "cTribNac": "041601",
        "cTribMun": "001",
        "tributos": {"pTotTribSN": "6.00"},
    },
    "dados_nota": {"serie": "1", "numero": "1", "valor": 1.0, "descricao": "Serviço"},
}


@pytest.fixture
def config_dict() -> dict[str, Any]:
    """Cópia profunda da config válida — mutável sem vazar entre testes."""
    return copy.deepcopy(CONFIG_VALIDA)


def gerar_pfx_teste(senha: str = "0000", cn: str = "TESTE PYNFSE:11222333000181") -> bytes:
    """Gera um .pfx **self-signed descartável** (cifra moderna) para teste.
    NÃO é certificado ICP-Brasil nem tem identidade real — só material de teste.
    `datetime` é determinístico (sem now()) para não depender do relógio."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    inicio = _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(inicio)
        .not_valid_after(inicio + _dt.timedelta(days=730))
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b"pynfse-teste", key, cert, None,
        serialization.BestAvailableEncryption(senha.encode()),
    )


@pytest.fixture
def pfx_teste(tmp_path: Path) -> tuple[Path, str]:
    """Caminho de um .pfx de teste em disco + sua senha."""
    senha = "0000"
    caminho = tmp_path / "teste.pfx"
    caminho.write_bytes(gerar_pfx_teste(senha))
    return caminho, senha

"""Leitura do certificado A1 (.pfx / PKCS#12). Lib: `cryptography`.

⚠️ Gotcha ICP-Brasil (docs/conhecimento-fiscal.md §9): certificados A1 ICP-Brasil
usam cifras legadas (RC2/3DES) que o OpenSSL 3 desabilita por padrão. Se a leitura
falhar, **NÃO assuma "senha errada"** — pode ser o bloqueio legado. Aqui:
  1. tenta ler direto com `cryptography` (cobre a maioria);
  2. se falhar, tenta um fallback best-effort via `openssl pkcs12 -legacy` (quando o
     binário existe) — se ISSO funciona, era cifra legada (e recuperamos);
  3. senão, levanta `CertificadoError` deixando as DUAS causas possíveis explícitas.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives.serialization.pkcs12 import PKCS12KeyAndCertificates
from cryptography.x509.oid import NameOID

from .config import Certificado as CertConfig


class CertificadoError(Exception):
    """Falha ao abrir/usar o certificado A1."""


class Certificado:
    """Abre o .pfx e expõe chave privada + certificado para assinatura e mTLS."""

    def __init__(self, cfg: CertConfig):
        self.cfg = cfg
        self._carregado: PKCS12KeyAndCertificates | None = None
        self.legado: bool = False  # True se foi preciso o fallback de cifra legada

    # ── leitura ─────────────────────────────────────────────────────────────
    def carregar(self) -> Certificado:
        """Lê o .pfx. Idempotente. Ver gotcha legado acima."""
        if self._carregado is not None:
            return self
        caminho = Path(self.cfg.path)
        if not caminho.exists():
            raise CertificadoError(f"certificado não encontrado: {caminho}")
        data = caminho.read_bytes()
        senha = self.cfg.senha.encode()
        try:
            self._carregado = pkcs12.load_pkcs12(data, senha)
        except ValueError as e:
            recuperado = self._tentar_legado(data, senha)
            if recuperado is None:
                raise CertificadoError(
                    "falha ao abrir o .pfx. Pode ser (a) senha incorreta OU (b) cifra "
                    "legada ICP-Brasil (RC2/3DES) bloqueada pelo OpenSSL — NÃO é "
                    "necessariamente senha errada (conhecimento-fiscal §9). "
                    f"Detalhe: {e}"
                ) from e
            self._carregado = recuperado
            self.legado = True
        if self._carregado.cert is None or self._carregado.cert.certificate is None:
            raise CertificadoError("o .pfx não contém um certificado")
        return self

    def _tentar_legado(self, data: bytes, senha: bytes) -> PKCS12KeyAndCertificates | None:
        """Best-effort: usa o `openssl` do sistema com o provedor `-legacy` para
        reembalar o .pfx num formato que a `cryptography` lê. Devolve None se não der."""
        openssl = shutil.which("openssl")
        if not openssl:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            pfx = Path(tmp) / "in.pfx"
            pem = Path(tmp) / "out.pem"
            pfx.write_bytes(data)
            try:
                # legacy → PEM (cert+chave), depois recarrega na cryptography
                subprocess.run(
                    [openssl, "pkcs12", "-legacy", "-in", str(pfx), "-out", str(pem),
                     "-nodes", "-passin", f"pass:{senha.decode()}"],
                    check=True, capture_output=True, timeout=30,
                )
                pem_bytes = pem.read_bytes()
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                return None
            key = serialization.load_pem_private_key(pem_bytes, password=None)
            if not isinstance(key, rsa.RSAPrivateKey):  # A1 ICP-Brasil é sempre RSA
                return None
            cert = x509.load_pem_x509_certificate(pem_bytes)
            # reembala num PKCS12 moderno em memória p/ uniformizar o tipo de retorno
            novo = pkcs12.serialize_key_and_certificates(
                b"pynfse", key, cert, None, serialization.BestAvailableEncryption(senha),
            )
            return pkcs12.load_pkcs12(novo, senha)

    # ── acesso ────────────────────────────────────────────────────────────────
    def _exigir(self) -> PKCS12KeyAndCertificates:
        if self._carregado is None:
            self.carregar()
        assert self._carregado is not None
        return self._carregado

    @property
    def certificado_x509(self) -> x509.Certificate:
        cert = self._exigir().cert
        assert cert is not None
        return cert.certificate

    @property
    def validade(self) -> datetime:
        """Fim da validade (UTC) do certificado."""
        return self.certificado_x509.not_valid_after_utc

    @property
    def titular(self) -> str:
        """Common Name do titular (em A1 ICP-Brasil costuma ser 'NOME:CNPJ')."""
        attrs = self.certificado_x509.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return str(attrs[0].value) if attrs else ""

    @property
    def cnpj(self) -> str | None:
        """CNPJ/CPF do titular, extraído do CN ICP-Brasil ('NOME:DOC'), se houver."""
        cn = self.titular
        if ":" in cn:
            doc = "".join(ch for ch in cn.rsplit(":", 1)[1] if ch.isdigit())
            return doc or None
        return None

    def como_pem(self, destino_dir: str | Path) -> tuple[str, str]:
        """Exporta (cert_pem_path, key_pem_path) para o mTLS via `requests`.
        Arquivos temporários — nunca versionar (ficam em `destino_dir`)."""
        p12 = self._exigir()
        assert p12.cert is not None and p12.key is not None
        destino = Path(destino_dir)
        destino.mkdir(parents=True, exist_ok=True)
        cert_path = destino / "cert.pem"
        key_path = destino / "key.pem"
        cert_path.write_bytes(p12.cert.certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            p12.key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        return str(cert_path), str(key_path)

"""Leitura do certificado A1 (.pfx / PKCS#12). Lib: `cryptography`.

⚠️ Gotcha ICP-Brasil (docs/conhecimento-fiscal.md §9): certificados A1 ICP-Brasil
usam cifras legadas (RC2/3DES) que o OpenSSL 3 desabilita por padrão. Se a leitura
falhar, **NÃO assuma "senha errada"** — pode ser o bloqueio legado. Aqui:
  1. tenta ler direto com `cryptography` (cobre a maioria);
  2. se falhar, tenta um fallback best-effort via `openssl pkcs12 -legacy` (quando o
     binário existe) — se ISSO funciona, era cifra legada (e recuperamos). A senha vai
     ao `openssl` pela ENTRADA PADRÃO, nunca na linha de comando (que qualquer processo
     da máquina lê em `/proc/<pid>/cmdline`), e o resultado volta pela saída padrão: a
     chave privada não é gravada em claro em disco;
  3. senão, levanta `CertificadoError` deixando as DUAS causas possíveis explícitas.

O .pfx recuperado do fallback é reembalado num PKCS#12 moderno (mesma senha):
`pkcs12_bytes()` o devolve, para a assinatura e o mTLS usarem o MESMO material que este
objeto leu (sem isso, o objeto abria e a emissão relia o arquivo original e falhava).

Quem é o titular: `documento` (CNPJ ou CPF) e `tipo_documento` ("CNPJ" | "CPF"). O CNPJ sai
do CN ICP-Brasil ("NOME:CNPJ"); sem o ":", de um CNPJ válido dentro do CN; sem ele, da
extensão SubjectAlternativeName (otherName 2.16.76.1.3.3 = CNPJ da PJ; 2.16.76.1.3.1 = dados
da pessoa física, de onde sai o CPF).
"""

from __future__ import annotations

import re
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

from . import documentos
from .config import Certificado as CertConfig

#: otherName da SAN (ICP-Brasil, DOC-ICP-04): o CNPJ da pessoa jurídica titular (e-CNPJ).
OID_SAN_CNPJ = "2.16.76.1.3.3"
#: otherName da SAN (ICP-Brasil): dados da pessoa física titular (e-CPF) — nascimento
#: (DDMMAAAA, 8) + CPF (11) + …
OID_SAN_PF = "2.16.76.1.3.1"

_RE_CNPJ = re.compile(r"[0-9A-Z]{12}[0-9]{2}")
_RE_CPF = re.compile(r"[0-9]{11}")
# Um CNPJ (numérico ou alfanumérico) solto no meio do CN, sem letra/dígito colado dos lados.
_RE_CNPJ_NO_CN = re.compile(r"(?<![0-9A-Z])[0-9A-Z]{12}[0-9]{2}(?![0-9A-Z])")


class CertificadoError(Exception):
    """Falha ao abrir/usar o certificado A1."""


def tipo_do_documento(doc: str | None) -> str | None:
    """"CNPJ" (14 posições, numérico ou alfanumérico), "CPF" (11 dígitos) ou None."""
    d = (doc or "").strip().upper()
    if _RE_CNPJ.fullmatch(d):
        return "CNPJ"
    if _RE_CPF.fullmatch(d):
        return "CPF"
    return None


def _der_conteudo(dados: bytes) -> bytes | None:
    """O conteúdo de UM elemento DER (tag + tamanho + conteúdo). Um invólucro explícito
    `[0]` (0xA0) é aberto uma vez. None se os bytes não forem DER."""
    for _ in range(2):
        if len(dados) < 2:
            return None
        tag, tam = dados[0], dados[1]
        ini = 2
        if tam & 0x80:
            n = tam & 0x7F
            if n == 0 or n > 4 or len(dados) < 2 + n:
                return None
            tam = int.from_bytes(dados[2:2 + n], "big")
            ini = 2 + n
        conteudo = dados[ini:ini + tam]
        if len(conteudo) != tam:
            return None
        if tag == 0xA0:
            dados = conteudo
            continue
        return conteudo
    return None


def _san_other_names(cert: x509.Certificate) -> dict[str, str]:
    """{OID: texto} dos otherName da SAN (só ASCII imprimível; o resto é descartado)."""
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return {}
    achados: dict[str, str] = {}
    for nome in san.get_values_for_type(x509.OtherName):
        conteudo = _der_conteudo(nome.value)
        if conteudo is None:
            continue
        texto = "".join(chr(b) for b in conteudo if 0x20 <= b < 0x7F)
        achados[nome.type_id.dotted_string] = texto
    return achados


class Certificado:
    """Abre o .pfx e expõe chave privada + certificado para assinatura e mTLS."""

    def __init__(self, cfg: CertConfig):
        self.cfg = cfg
        self._carregado: PKCS12KeyAndCertificates | None = None
        self._bytes: bytes | None = None   # o PKCS#12 que a assinatura e o mTLS devem usar
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
            self._bytes = data
        except ValueError as e:
            recuperado = self._tentar_legado(data, senha)
            if recuperado is None:
                raise CertificadoError(
                    "falha ao abrir o .pfx. Pode ser (a) senha incorreta OU (b) cifra "
                    "legada ICP-Brasil (RC2/3DES) bloqueada pelo OpenSSL — NÃO é "
                    "necessariamente senha errada (conhecimento-fiscal §9). "
                    f"Detalhe: {e}"
                ) from e
            self._bytes, self._carregado = recuperado
            self.legado = True
        if self._carregado.cert is None or self._carregado.cert.certificate is None:
            raise CertificadoError("o .pfx não contém um certificado")
        return self

    def _tentar_legado(self, data: bytes,
                       senha: bytes) -> tuple[bytes, PKCS12KeyAndCertificates] | None:
        """Best-effort: usa o `openssl` do sistema com o provedor `-legacy` para
        reembalar o .pfx num formato que a `cryptography` lê. Devolve None se não der.

        A senha vai pela entrada padrão (`-passin stdin`) e o PEM volta pela saída padrão:
        nem a senha aparece na linha de comando, nem a chave em claro toca o disco. Só o
        .pfx ORIGINAL (cifrado, igual ao arquivo de quem chamou) passa por um temporário."""
        openssl = shutil.which("openssl")
        if not openssl:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            pfx = Path(tmp) / "in.pfx"
            pfx.write_bytes(data)
            try:
                r = subprocess.run(
                    [openssl, "pkcs12", "-legacy", "-in", str(pfx), "-nodes",
                     "-passin", "stdin"],
                    input=senha + b"\n", check=True, capture_output=True, timeout=30,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                return None
        pem_bytes = r.stdout
        try:
            key = serialization.load_pem_private_key(pem_bytes, password=None)
            cert = x509.load_pem_x509_certificate(pem_bytes)
        except ValueError:
            return None
        if not isinstance(key, rsa.RSAPrivateKey):  # A1 ICP-Brasil é sempre RSA
            return None
        # reembala num PKCS12 moderno em memória p/ uniformizar o tipo de retorno
        novo = pkcs12.serialize_key_and_certificates(
            b"pynfse", key, cert, None, serialization.BestAvailableEncryption(senha),
        )
        return novo, pkcs12.load_pkcs12(novo, senha)

    # ── acesso ────────────────────────────────────────────────────────────────
    def _exigir(self) -> PKCS12KeyAndCertificates:
        if self._carregado is None:
            self.carregar()
        assert self._carregado is not None
        return self._carregado

    def pkcs12_bytes(self) -> bytes:
        """O PKCS#12 a usar na assinatura e no mTLS (mesma senha do arquivo): o próprio
        arquivo quando a `cryptography` o leu; o reembalado quando foi preciso o fallback
        de cifra legada — o mesmo material que este objeto abriu."""
        self._exigir()
        assert self._bytes is not None
        return self._bytes

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
    def documento(self) -> str | None:
        """CNPJ ou CPF do titular (sem máscara; letras do CNPJ alfanumérico preservadas).

        Ordem: o que vem depois do ':' do CN ICP-Brasil; sem ':', um CNPJ com DV válido
        dentro do CN; sem ele, a SAN (2.16.76.1.3.3 → CNPJ; 2.16.76.1.3.1 → CPF). Para
        saber se é CNPJ ou CPF, use `tipo_documento`."""
        cn = self.titular
        if ":" in cn:
            # CNPJ alfanumérico (NT 2025.001): preserva letras do doc (e-CPF segue só dígitos).
            doc = "".join(ch for ch in cn.rsplit(":", 1)[1] if ch.isalnum()).upper()
            if doc:
                return doc
        for m in _RE_CNPJ_NO_CN.finditer(cn.upper()):
            if documentos.cnpj_valido(m.group(0)):
                return m.group(0)
        san = _san_other_names(self.certificado_x509)
        cnpj = documentos.norm_documento(san.get(OID_SAN_CNPJ, ""))[:14]
        if tipo_do_documento(cnpj) == "CNPJ":
            return cnpj
        cpf = documentos.digitos(san.get(OID_SAN_PF, "")[8:19])
        if tipo_do_documento(cpf) == "CPF" and set(cpf) != {"0"}:
            return cpf
        return None

    @property
    def tipo_documento(self) -> str | None:
        """"CNPJ" (e-CNPJ, certificado de empresa), "CPF" (e-CPF, de pessoa física) ou None.

        É o que separa, sem ambiguidade, o certificado da empresa do certificado do sócio:
        `documento` (e `cnpj`, o nome antigo) devolve o que houver, CNPJ ou CPF."""
        return tipo_do_documento(self.documento)

    @property
    def cnpj(self) -> str | None:
        """CNPJ/CPF do titular — o mesmo que `documento` (nome mantido por compatibilidade).

        ☠️ Apesar do nome, um e-CPF devolve o CPF. Quem precisa de um e-CNPJ confere
        `tipo_documento == "CNPJ"`."""
        return self.documento

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

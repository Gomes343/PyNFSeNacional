#!/usr/bin/env bash
# Regenera o gabarito (DPS assinado pela referência PHP) usado pelo golden test.
#
# Passo só do MANTENEDOR (não roda no CI; o CI usa o XML já versionado). Requer a
# implementação de referência em PHP — que é PRIVADA e NÃO acompanha este repositório.
# Aponte para ela via a variável de ambiente NFSE_PHP_REF. Usa também um .pfx de teste
# DESCARTÁVEL (gerado aqui — NÃO é ICP-Brasil nem tem identidade real).
#
# Por que regenerar: se a lógica fiscal do PHP mudar (ordem de elemento, verAplic,
# formato), o gabarito tem de ser refeito para o byte-diff continuar honesto.
#
# Uso:  NFSE_PHP_REF=/caminho/para/o/php bash tests/golden/regenerar_gabarito.sh
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
API="${NFSE_PHP_REF:?defina NFSE_PHP_REF apontando para a implementação de referência em PHP (privada)}"
PY="$RAIZ/.venv/bin/python"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# 1) .pfx de teste descartável (cifra moderna) a partir do config do gabarito
"$PY" - "$AQUI/gabarito_config.json" "$TMP" <<'PYEOF'
import sys, json, datetime
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
cfg = json.load(open(sys.argv[1])); tmp = Path(sys.argv[2])
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TESTE PYNFSE:" + cfg["prestador"]["cnpj"])])
ini = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(ini).not_valid_after(ini + datetime.timedelta(days=730))
        .sign(key, hashes.SHA256()))
(tmp / "teste.pfx").write_bytes(pkcs12.serialize_key_and_certificates(
    b"t", key, cert, None, serialization.BestAvailableEncryption(b"0000")))
cfg = dict(cfg); cfg["certificado"] = {"path": str(tmp / "teste.pfx"), "senha": "0000"}
(tmp / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
PYEOF

# 2) build + assina (sem enviar) via referência PHP privada.
# Adapte ao entrypoint da SUA referência: ele recebe o config.json e imprime no stdout um
# JSON {"arquivo": "<caminho do DPS assinado>"} (é o que o passo seguinte lê).
cd "$API"
SAIDA="$(./montar_dps "$TMP/config.json")"
ARQ="$("$PY" -c "import json,sys; print(json.loads(sys.argv[1])['arquivo'])" "$SAIDA")"
cp "$ARQ" "$AQUI/gabarito_dps_assinado.xml"
echo "gabarito atualizado: $AQUI/gabarito_dps_assinado.xml"
echo "NOTA: dhEmi/dCompet do gabarito são o instante da geração; o golden os extrai do XML."

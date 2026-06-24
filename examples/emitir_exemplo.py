"""Quickstart — a API pública deste pacote.

O pipeline está implementado (alpha): este script emite de fato, desde que você aponte
para um config real de cliente (`config/cliente.json`, fora do git) com um certificado A1.
Em `homologacao` a nota é de teste, sem validade jurídica. Valide cada emissão.

Rodar:  python examples/emitir_exemplo.py
"""

from pynfsenacional import Emissor

# Aponte para o config real do cliente (fora do git). Ver examples/config-exemplo.json.
emissor = Emissor("config/cliente.json", ambiente="homologacao")

nota = emissor.emitir(
    valor=150.00,
    descricao="Sessão de psicoterapia",
    tomador={"cpf_cnpj": "00000000000", "nome": "Fulano de Tal"},
)

print("emitida:", nota.emitida)
print("nNFSe:  ", nota.numero_nfse)
print("chave:  ", nota.chave_acesso)

# DANFSe (PDF) gerado localmente a partir do XML da nota:
nota.danfse("nota.pdf")

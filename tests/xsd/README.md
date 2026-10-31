# Esquemas oficiais da DPS (só para os testes)

Cópias dos pacotes publicados pela SE/CGNFS-e em gov.br/nfse (documentação técnica). Só os quatro
arquivos que a DPS usa. A suíte (`tests/test_leiaute.py`) valida contra eles toda DPS que a lib monta.

| Pasta | Pacote | Onde vale |
|---|---|---|
| `20260209/` | `nfse-esquemas_xsd-v1-01-20260209.zip` (documentação atual) | produção |
| `20261020/` | `esquemas_prod_restrita_20261020.zip` (NT 009) | produção restrita (homologação), desde 31/10/2026 |

**Um ajuste, só no `20260209/tiposSimples_v1.01.xsd`:** o padrão de `TSSerieDPS` vem como
`^0{0,4}\d{1,5}$`. Em XSD, `^` e `$` não são âncoras, são caracteres literais, e num validador
estrito (libxml2, o do lxml) nenhuma série passa. O SEFIN aceita, então o validador dele trata os
dois como âncoras. A cópia daqui tira os dois caracteres (`0{0,4}\d{1,5}`), que é o que o SEFIN
aplica; o pacote da NT 009 já corrigiu o padrão. Nada mais foi alterado.

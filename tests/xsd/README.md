# Esquemas oficiais da DPS (só para os testes)

Cópias dos pacotes publicados pela SE/CGNFS-e em gov.br/nfse (documentação técnica). Só os quatro
arquivos que a DPS usa. A suíte (`tests/test_leiaute.py`) valida contra eles toda DPS que a lib monta.

| Pasta | Pacote | Onde vale |
|---|---|---|
| `20260209/` | `nfse-esquemas_xsd-v1-01-20260209.zip` (documentação atual) | produção |
| `20261020/` | `esquemas_prod_restrita_20261020.zip` (NT 009) | produção restrita (homologação), desde 31/10/2026 |
| `nt009-sn/` | **NÃO é pacote oficial** — o `20261020/` mais dois elementos do Anexo VI v1.04.01 | nenhum ambiente ainda (leiaute `nt009-sn`, só por config) |

**Um ajuste, só no `20260209/tiposSimples_v1.01.xsd`:** o padrão de `TSSerieDPS` vem como
`^0{0,4}\d{1,5}$`. Em XSD, `^` e `$` não são âncoras, são caracteres literais, e num validador
estrito (libxml2, o do lxml) nenhuma série passa. O SEFIN aceita, então o validador dele trata os
dois como âncoras. A cópia daqui tira os dois caracteres (`0{0,4}\d{1,5}`), que é o que o SEFIN
aplica; o pacote da NT 009 já corrigiu o padrão. Nada mais foi alterado.

**O `nt009-sn/` não é oficial.** A NT 009 (§2.4, Anexo VI v1.04.01 de 11/09/2026) criou dois campos
do Simples Nacional que nenhum pacote de esquemas publicou até 17/11/2026: `regApIBSCBSSN` (no
`TCRegTrib`, depois do `regApTribSN`, domínio 1–3) e `cAtvSN` (no `TCCServ`, depois do `cNBS` e
antes do `cIntContrib`, domínio 07–14 e 90). A pasta é a cópia do `20261020/` com esses dois
elementos e os dois tipos simples (`TSRegApIBSCBSSN`, `TSCodAtvSN`), marcados "[nt009-sn - NAO
oficial]" no próprio arquivo — posições e domínios tirados das linhas 153 e 231 do leiaute do
Anexo VI. Serve para a suíte provar a ORDEM em que a lib os escreve. Quando o pacote oficial sair,
esta pasta é trocada por ele (e o leiaute ganha a data do pacote).

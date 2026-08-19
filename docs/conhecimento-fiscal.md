# Conhecimento fiscal — NFS-e Nacional (DPS) + DANFSe

> Este documento é o **coração** do projeto: o conhecimento fiscal ganho a sangue emitindo notas
> reais no Sistema Nacional NFS-e. A implementação Python muda de linguagem, mas **estas regras
> não mudam** — são do SEFIN, não da linguagem.
>
> Cada regra aqui foi **paga com nota real**: nasceu na operação diária da
> [**GT Contabilidade**](https://gtcontabilidade.com), escritório contábil que emite NFS-e pelo
> padrão nacional para clientes em municípios diferentes, e que decidiu publicar o que aprendeu em
> vez de guardar. Nenhum dado de contribuinte aparece aqui — só a regra, que serve a todo mundo.

---

## 1. As duas APIs do governo (a confusão da NT-008/2026)

Existem **duas APIs distintas**, sempre confundidas:

1. **API de emissão (SEFIN Nacional)** — *viva, é o futuro.* Recebe a **DPS** (Declaração de
   Prestação de Serviço) assinada e devolve a **NFS-e**. É por aqui que se emite.
2. **API de geração do DANFSe/PDF (ADN)** — **descontinuada em 01/07/2026** pela NT-008/2026
   (renderizar PDF no servidor do governo é pesado/instável, vive dando 502). A partir daí cada
   emitente **gera o PDF localmente** (layout DANFSe v2.0).

**Decisão deste projeto:** emitir por API **e** gerar o DANFSe **localmente** (antecipando o prazo).

### Ambientes
| Workflow | SEFIN | `tpAmb` | Validade |
|---|---|---|---|
| 🧪 Homologação (teste) | `sefin.producaorestrita.nfse.gov.br` | 2 | sem validade jurídica |
| 🟢 Produção (nota real) | `sefin.nfse.gov.br` | 1 | nota real |

> **`ambGer` ≠ ambiente.** `ambGer` (1=Prefeitura, 2=Sistema Nacional) — **toda** nota nacional tem
> `ambGer=2`. O indicador Produção/Homologação é o **`tpAmb`** (1/2). Confundir os dois faz o DANFSe
> rotular nota de produção como "SEM VALIDADE JURÍDICA" (ver §6).

---

## 2. Fluxo de emissão (pipeline)

```
config do cliente (JSON)
   │
   ▼
montar DPS (XML, leiaute AnexoI)         ← toda a lógica fiscal mora aqui (§4)
   │
   ▼
assinar (XMLDSIG) com o certificado A1   ← assinatura enveloped no nó infDPS
   │
   ▼
gzip + base64  →  POST /nfse  (mTLS, cert do emitente)
   │
   ▼
SEFIN Nacional  →  NFS-e (XML)           ← nNFSe (número fiscal) atribuído pelo SEFIN (§5)
   │
   ▼
render DANFSe local (PDF)                ← a partir do XML da NFS-e (§6)
```

**Idempotência nativa:** consultar a DPS por `Id` (`verificarDps` / `GET /dps/{id}`) **antes** de
reemitir evita duplicar — substitui qualquer guard caseiro.

---

## 3. ★ Schema de configuração do cliente

Cada prestador é descrito por um JSON. Campos marcados ★ são **obrigatórios**. Exemplo anotado
(dados **fictícios** — o real nunca vai para o git):

```jsonc
{
  "id": "exemplo",
  "nome_cliente": "EMPRESA EXEMPLO LTDA",
  "ambiente": "homologacao",          // default p/ execução manual

  "certificado": {                    // ★ certificado A1 ICP-Brasil do PRÓPRIO prestador
    "path": "certs/exemplo.pfx",      //   (.pfx — gitignored)
    "senha": "0000"
  },

  "prestador": {
    "cnpj": "00000000000000",         // ★ 14 dígitos
    "codigo_municipio": "0000000",    // ★ IBGE 7 díg do município do EMITENTE
    "uf": "RJ",                        //   referência
    "inscricao_municipal": null,      //   só se o município exigir na DPS

    "regime": {                        // ★ regime tributário
      "opSimpNac": 3,                  //   1=Não Optante · 2=MEI · 3=Optante ME/EPP (Simples)
      "regApTribSN": 1,                //   apuração do SN (se optante): 1=fed+mun pelo SN ·
                                       //   2=fed SN, ISSQN normal · 3=MEI
      "regEspTrib": 0                  //   regime especial (0=Nenhum)
    }
    // NÃO enviar endereço/nome do prestador quando ele é o emitente (tpEmit=1): E0128/E0121 (§4)
  },

  "servico": {
    "codigo_municipio_prestacao": "0000000",  // ★ local da prestação (IBGE; geralmente = emitente)
    "cTribNac": "041601",             // ★ Código de Tributação NACIONAL — 6 díg (LC116)
    "cTribMun": "001",                // ★ Código de Tributação MUNICIPAL (desdobro do município)
    "descricao_padrao": "Serviço Prestado",
    "tributos": {
      "pTotTribSN": "6.00"            // ★ se Simples: % efetiva do Simples Nacional
      // "tribISSQN": 1,             //   opcional (default 1 = tributável)
      // "tpRetISSQN": 1             //   opcional (default 1 = não retido)
    }
  },

  "dados_nota": {                      // bloco de EXEMPLO p/ teste manual; em produção é
    "serie": "1",                      //   sobrescrito pelos dados da emissão (valor/desc/tomador)
    "numero": "1",                     //   semente do contador nDPS (§5)
    "valor": 1.00,
    "descricao": "Serviço de exemplo",
    "tomador": { "tipo": "CPF", "cpf_cnpj": "00000000000", "xNome": "TOMADOR EXEMPLO" }
  }
}
```

### O que cada cliente precisa fornecer
| Dado | Origem |
|---|---|
| Certificado A1 (.pfx) + senha | do cliente (anuência); validade conta — renovar antes de vencer |
| CNPJ | cadastro do cliente |
| Código do município (IBGE) | município de atuação do prestador |
| Regime: `opSimpNac` / `regApTribSN` | contabilidade (Simples? MEI ou ME/EPP? qual apuração?) |
| `cTribNac` (6 díg) | item da LC116 da atividade (mesmo código usado no portal hoje) |
| `cTribMun` (desdobro municipal) | o que o município administra p/ aquele `cTribNac` (§4) |
| `pTotTribSN` (% Simples) | alíquota efetiva do Simples (contabilidade) |
| Inscrição Municipal | **o CNC decide, por CNPJ** — não é "por município" (§10) |

### Pego automaticamente pelo SEFIN (NÃO enviar)
- **Nome e endereço do prestador** (do cadastro nacional) → enviar dá **E0128/E0121**.
- **Número fiscal `nNFSe`** — o SEFIN atribui, continuando a sequência real do prestador (§5).

### ★ MEI (`opSimpNac=2`) — rotina de emissão DIFERENTE do ME/EPP
O MEI é optante do Simples, mas **não** segue a mesma DPS do ME/EPP (`opSimpNac=3`). O motor precisa
**chavear pelo `opSimpNac`** (validado contra a nota real do EmissorWeb do governo — um MEI de Ibirité/MG):

| Elemento | ME/EPP optante (`opSimpNac=3`) | **MEI (`opSimpNac=2`)** |
|---|---|---|
| `regTrib/regApTribSN` | presente (ex.: `1`) | **omitido** — não se aplica ao MEI |
| `valores/trib/totTrib` | `pTotTribSN` (% do Simples) | **`indTotTrib=0`** — MEI é **isento** de declarar o valor aproximado dos tributos (**Decreto 8.264/2014**) |
| `cServ/cTribMun` | conforme o município (senão E0312) | frequentemente **ausente** (o município pode não usar desdobro para o serviço do MEI) |

- **Por que `indTotTrib` e não `pTotTribSN`:** o E0712 proíbe `indTotTrib` para **ME/EPP**, mas o MEI
  é justamente o caso de **não informar** (Decreto 8.264/2014). Usar `pTotTribSN` num MEI destoa da
  nota real e informa um percentual que não se aplica.
- **Não Optante (`opSimpNac=1`)** também usa `indTotTrib`; só o **ME/EPP (3)** usa `pTotTribSN`.
- O motor implementa esse chaveamento em `dps.py` (`regTrib` e `totTrib`) e o validador só exige
  `pTotTribSN` quando `opSimpNac==3`. Regressão: `test_mei_usa_indtottrib_e_omite_regaptribsn`.

---

## 4. ★ Tabela de erros do SEFIN (a jornada — todos resolvidos)

A regra de cada erro é **fiscal**, vale para qualquer linguagem. A "Solução" descreve o que mandar
(ou deixar de mandar) na DPS.

| Código | Sintoma | Causa | Solução |
|---|---|---|---|
| **E0008** | data de emissão "posterior ao processamento" | máquina em UTC × SEFIN em Brasília | fixar fuso **America/Sao_Paulo** antes de gerar `dhEmi` |
| **E0312** | "código não administrado pelo município" | mandava só `cTribNac` | enviar **`cTribNac` + `cTribMun`** (o município administra a COMBINAÇÃO) |
| **E0128** | "endereço do prestador não deve ser informado" | prestador=emitente (`tpEmit=1`) | **omitir** o endereço do prestador (SEFIN puxa do cadastro) |
| **E0121** | "nome/razão do prestador não deve ser informado" | idem | **omitir** o nome — bloco do prestador = só CNPJ + regime |
| **E0712** | "ME/EPP: `indTotTrib` não pode ser informado" | **ME/EPP** (`opSimpNac=3`) não usa `indTotTrib` | ME/EPP → **`totTrib/pTotTribSN`** (% efetiva do SN). ⚠️ **MEI (`opSimpNac=2`) é o oposto**: usa `indTotTrib=0` (Decreto 8.264/2014) — ver §3 "MEI" |
| **E1235** | "trib sem `totTrib`" | `totTrib` é obrigatório | sempre enviar `totTrib` (`pTotTribSN` p/ Simples; `indTotTrib` p/ não optante) |
| **E1235** | "Pattern TSCodTribNac" | `cTribNac` com 9 díg | `cTribNac` é **6 díg**; o desdobro vai em `cTribMun` |
| **E1235** | "Falha no esquema (verAplic)" | `verAplic` > 20 chars | **`verAplic` ≤ 20** caracteres |
| **E1235** | "`toma` incompleto (expected CAEPF, IM, xNome)" | tomador só com CPF/CNPJ | tomador identificado **EXIGE nome** (`xNome`); ver §7 |
| **E0116** | "a IM deve ser informada… conforme CNC do município emissor" | o CNPJ **tem** Inscrição Municipal no CNC e a DPS foi sem ela | informar a IM do prestador — ver §10 |
| **E0120** | "IM não deve ser informada, pois não existem informações complementares no CNC" | mandou IM onde o CNC **não** tem esse CNPJ (ou o município não usa CNC) | **omitir** a IM (vazio/`null`) — ver §10 |
| **E0315** | "não é permitido informar 000" (`cTribMun`) | município **sem desdobro** municipal | **omitir** `cTribMun` (é `minOccurs=0`) |
| **E0676** | "não é permitido preencher os tributos federais quando o emitente é MEI" | bloco `tribFed` numa DPS de **MEI** | MEI recolhe no DAS-SIMEI → **omitir `tribFed`** (§3) |
| **E0240** | "o CEP informado para o endereço nacional do tomador não existe ou não pertence ao município" | quase nunca é digitação: é o **CEP geral do município** (`xxxxx-000`) herdado de cadastro automático | §11 |

### Código de serviço: `cTribNac` + `cTribMun`
O código do portal no formato `00.00.00.000` decompõe em:
- **`cTribNac`** = os 6 primeiros dígitos (2 item + 2 subitem + 2 desdobro), ex.: `04.16.01` → `041601`.
- **`cTribMun`** = o desdobro municipal, ex.: o `.001` final → `001`.

O município administra a **combinação**. Há uma consulta de alíquota/serviço administrado (por
município + código + data) para descobrir/confirmar o `cTribMun` — confirmar sempre com a contabilidade.

---

## 5. Numeração: nDPS × nNFSe (importante)

- **nNFSe** (número fiscal da NFS-e) é **atribuído pelo SEFIN**, continuando a sequência REAL do
  prestador. **Não controlamos nem enviamos.** (Prova real: nDPS 118 → o SEFIN devolveu nNFSe 147.)
- **nDPS** (número da DPS, nosso documento) é **obrigatório** (faz parte do `Id` assinado), mas é só
  um **contador interno** — pode auto-incrementar livremente, sem relação com o número fiscal.
- Implementação: **contador por ambiente** (`numero_<id>_<homologacao|producao>.txt`), incrementa só
  quando a nota foi de fato emitida. Testes em homologação **não** consomem a numeração de produção.

### ★ Quando o prestador JÁ emitia por outro sistema — use uma série dedicada

O `Id` da DPS é `município + CNPJ + **série** + nDPS`. Se o CNPJ já emitiu pelo portal do governo (ou
por outro software) com **série 1, nDPS 1..N**, começar nosso contador em 1 na mesma série **repete um
`Id` que já existe** — e o SEFIN, corretamente, devolve a nota **já emitida** em vez de uma nova. Não é
erro: é a idempotência funcionando contra você. E é traiçoeiro porque *parece* que emitiu.

Duas coisas a fazer antes da primeira nota de um prestador que já emitia:

1. **Descobrir as séries que ele já usa** — a caixa **DF-e** do prestador entrega os XMLs das notas
   emitidas, com série e número reais (§13). Na prática aparecem séries "de sistema" bem fora do óbvio
   (900, 70000…), não só a 1.
2. **Escolher uma série DEDICADA** que ele não use, e fixá-la na config. Assim a numeração da sua
   emissão fica **independente** da que o contribuinte gera por fora, para sempre — inclusive se ele
   voltar a emitir pelo portal no meio do mês.

> O contador local é por **(prestador, ambiente)** — ele **não** sabe de série. Trocar a série sem
> zerar/segregar o contador é outra forma de colidir.

---

## 6. DANFSe local (PDF) — gerado do XML da NFS-e

A API de PDF do governo (ADN) morre em 01/07/2026 → geramos o PDF localmente, a partir do XML
devolvido pelo SEFIN. Em Python a peça é a `BrazilFiscalReport` (DANFSE). Dois gotchas conhecidos
(da implementação de referência — verificar se a lib Python os reproduz):

1. **Rótulo de ambiente:** o teste de "sem validade jurídica" deve usar **`tpAmb===2`**, NÃO
   `ambGer===2`. Como toda nota nacional tem `ambGer=2`, usar `ambGer` marca **toda** nota como
   homologação/sem validade — inclusive as de produção. Regra: `homologacao = (tpAmb == 2)`.
2. **UF do "Local da Prestação":** resolver a sigla da UF pelo código IBGE do município de prestação
   (`cLocPrestacao`); sem isso o campo sai como `{município} / BR` (UF vazia).

Conteúdo do DANFSe: cabeçalho NFS-e + QR Code, chave de acesso, blocos Prestador / Tomador /
Serviço / ISSQN / Federal / IBS-CBS / Valores / Informações Complementares. A4 retrato.

---

## 7. Tomador — quando exige nome (E1235)

O SEFIN rejeita `<toma>` que tenha só CPF/CNPJ (**E1235**: `incomplete content ... expected
'CAEPF, IM, xNome'`). O portal-navegador preenchia o nome pela Receita; a **API não** (a consulta de
contribuinte é operação de município — o prestador recebe 404). Consequências para o pipeline:

- **Tomador identificado → precisa do `xNome`.** Obter de cadastro próprio (o usuário informa) ou,
  para CNPJ, da razão social pública (ex.: BrasilAPI) para não precisar perguntar.
- **Endereço do tomador é opcional** (`0-1`) — não exigido, mas **emitido quando fornecido**
  (desde 30/06/2026). O `<toma>` aceita, além de CPF/CNPJ + xNome, os campos OPCIONAIS na ordem
  do XSD: **`IM → end → fone → email`** (trocar a ordem = E1235). O `<end>` nacional é **bloco
  atômico** (tudo-ou-nada): `endNac(cMun 7díg, CEP 8díg) → xLgr → nro → xCpl? → xBairro`; faltando
  qualquer obrigatório (cMun/CEP/logradouro/bairro), omite o endereço inteiro. `fone` = só dígitos;
  `email` ≤ 80. Endereço no exterior (`endExt`) ainda não coberto.
- **Consumidor final / não identificado** → omitir o bloco `<toma>` por completo.

---

## 8. IBS/CBS (reforma tributária) — planejado

O **leiaute** da DPS já está em **1.01** (RTC — NT 004 v2.0 / NT 007); ver `VERSAO_DPS` em `dps.py`.
O grupo `IBSCBS` é **opcional no schema** (`minOccurs=0`) e o montador **ainda não o emite**.

**Cronograma:** a partir de **03/08/2026** o grupo IBS/CBS + validações passam a ser **obrigatórios**
na NFS-e Nacional (rejeição da DPS) — **porém só para Regime Regular** (Lucro Presumido/Real). O
**Simples Nacional é dispensado** do destaque em 2026: os campos do destaque do Simples só entram na
**NT 009** (sem data de produção), e o destaque do Simples só vale a partir de **2027**. Por isso,
para os perfis atualmente suportados (Simples), emite-se **sem** o grupo.

Quando entrar em escopo (um prestador de Regime Regular, ou mudança do SEFIN), acrescentar o grupo
(CST/cClassTrib, alíquotas IBS UF/Mun e CBS, `indZFMALC`) ao montador da DPS.

---

## 9. Dependências de sistema (cripto e PDF)

- **Leitura do `.pfx` ICP-Brasil:** certificados A1 ICP-Brasil usam cifras legadas (RC2/3DES) que o
  OpenSSL 3 desabilita por padrão. Na referência PHP isso exigiu `openssl-legacy.cnf` +
  `OPENSSL_CONF` (o SDK reportava "senha incorreta", enganoso). **Em Python**, validar se a
  `cryptography` (`load_key_and_certificates`) lê o `.pfx` direto; se topar com o mesmo bloqueio de
  cifra legada, é o ponto a tratar (não é "senha errada").
- **QR Code / PNG** no DANFSe: garantir as deps da lib de PDF.

---

## 10. ★ Inscrição Municipal do prestador: quem decide é o **CNC**, por **CNPJ**

Esta é a regra que mais custou tempo — e a que quase toda documentação erra, porque a intuição diz
"o município X exige IM". **Não existe isso.** Quem responde é o **CNC** (Cadastro Nacional de
Contribuintes) e ele responde **por CNPJ**: dois prestadores da **mesma cidade** podem exigir coisas
**opostas**.

São **três** situações, e todas as três aparecem na prática:

| Situação | `inscricao_municipal` | Se errar |
|---|---|---|
| Município **sem** cadastro no CNC | **vazio / `null`** — não mandar | **E0120** — "IM não deve ser informada, pois não existem informações complementares no CNC" |
| Município com CNC **e o CNPJ tem IM lá** | **mandar** a IM | **E0116** — "a IM deve ser informada… conforme CNC do município emissor" |
| Município com CNC, **mas aquele CNPJ não tem IM lá** | **vazio / `null`** — não mandar | — (emite limpo) |

A terceira linha é a que quebra a intuição: o município está anotado como "exige IM", e mesmo assim
**aquele** CNPJ emite sem. Por isso a config trata a IM como **opcional** e o montador **omite** o
elemento quando ela vem vazia (regressão `test_prestador_sem_im_omite_o_elemento`).

### Como descobrir sem chutar
1. **Leia o XML que o próprio contribuinte já emitiu** para aquele CNPJ (§13). Se o `<prest>` das
   notas dele leva `<IM>`, mande; se não leva, não mande. O portal é o espelho do CNC — isso é fato
   sobre o que o município **aceitou**, não suposição.
2. Só então, se ainda houver dúvida, a **nota canário** (§13).

> ⚠️ **Homologação MENTE sobre IM/CNC.** O ambiente de produção restrita chega a devolver **E0116
> com e sem** a IM, o que parece "bloqueio externo" e manda você caçar o problema no lugar errado.
> Para **IM, CNC e adesão do município**, o único ambiente que responde a verdade é **produção**.
> (No mesmo espírito: **nem todo município existe em homologação** — para muitos, não há teste
> possível antes da nota real.)

> ⚠️ **Nunca preencha a IM "de enfeite"** (`0000`, `ISENTO`, o CNPJ repetido…) só para satisfazer o
> campo. Ou é recusado — ou, muito pior, **passa**, e você acaba de emitir uma nota fiscal **real com
> dado falso**. Omitir é sempre mais seguro que inventar; a validação desta biblioteca **recusa**
> IM sem dígito significativo justamente por isso. Se vier E0116 de verdade, peça a IM à prefeitura.

---

## 11. E0240 — o CEP que passa em toda validação e **não existe**

> `[E0240] O CEP informado para o endereço nacional do tomador do serviço não existe ou não pertence
> ao município do endereço do tomador`

O reflexo é procurar erro de digitação na mensagem que originou a nota. Quase nunca é isso —
**ninguém digitou CEP**. O caminho real costuma ser este:

1. O tomador é novo e o cadastro dele é criado **automaticamente** a partir da consulta de CNPJ.
2. A Receita guarda, para muitas empresas, o **CEP geral do município** (o `xxxxx-000`) em vez do CEP
   da rua.
3. Esse CEP **não existe** como CEP de logradouro: serviços de consulta (ViaCEP e afins) devolvem
   erro para ele, e a **SEFIN recusa** a DPS.
4. Como o cadastro só é reconsultado quando o tomador está **sem** endereço, o valor ruim fica
   gravado e a nota falha **de novo** a cada tentativa — sem nada de útil na mensagem original.

**Confirmar em 10 segundos:** consultar o CEP (ex.: `https://viacep.com.br/ws/<cep>/json/`) — se
voltar erro, é isso. **Achar o certo:** busca por UF + cidade + logradouro que a própria Receita
informou, casando pelo **bairro**; com mais de um candidato em bairros diferentes, **não chute**.

**Por que a validação local não pega:** a validação desta biblioteca é de **formato** (CEP com 8
dígitos, `cMun` com 7, logradouro e bairro não vazios) — e o CEP geral passa em todos esses testes.
Validar **existência** exigiria rede, o que uma lib de emissão não deve fazer no meio do envio. A
contramedida é de operação: **varrer os CEPs cadastrados** contra um serviço de consulta e corrigir
**antes** de precisar emitir.

> Relacionado: o endereço do tomador é **bloco atômico** (§7) — faltando um obrigatório, a biblioteca
> **omite o endereço inteiro** e **registra um WARNING** dizendo quais campos faltaram (nunca os
> valores). Guarda silenciosa é bug com cara de sucesso.

---

## 12. PIS/COFINS: o CST default e o que o portal do contribuinte emite

No bloco `valores/trib/tribFed/piscofins/CST`:

| CST | Significado |
|---|---|
| `00` | Nenhum |
| `08` | Operação sem Incidência |

O default desta biblioteca é **`08`**, e ele **é aceito** pelo SEFIN — há muita nota real em produção
emitida assim. Mas existem contribuintes cujo **próprio portal** emite **`00`** em centenas de notas.
Nenhum dos dois é "o certo" universal: **o critério é o XML que aquele contribuinte já emitiu** (§13).

Configurável por prestador em `servico.tributos.piscofins_cst` (`"00"` ou `"08"`). Não propague o
valor de um contribuinte para os outros — cada um pede a sua conferência.

> **MEI é exceção total:** não emite o bloco `tribFed` (nem PIS/COFINS), sob pena de **E0676** — ele
> recolhe os federais no DAS-SIMEI (§3).

---

## 13. ★ Método: o XML que o contribuinte **já emitiu** é a fonte da verdade

A maior parte dos erros de configuração some quando se para de perguntar "qual código a atividade
dele usa?" e se passa a **ler as notas que ele já emitiu**. A caixa **DF-e** (distribuição de
documentos fiscais eletrônicos) entrega esses XMLs para o próprio contribuinte.

De um punhado de XMLs antigos saem, prontos e provados, quase todos os campos que travam a primeira
emissão:

| Campo | O que o XML antigo prova |
|---|---|
| `cTribNac` + `cTribMun` | a combinação que **aquele município administra** (evita E0312/E0315) |
| `<IM>` no `<prest>` | se o CNC tem IM para aquele CNPJ (§10) |
| `serie` / `nNFSe` | quais séries ele já usa — para escolher uma **dedicada** (§5) |
| `piscofins/CST` | `00` × `08` conforme o próprio emitente (§12) |
| `regTrib` | `opSimpNac` / `regApTribSN` / `regEspTrib` reais |

Isso vale mais que a resposta de qualquer pessoa envolvida: é o que o município **aceitou**, não o
que alguém acredita. Quando o dado do XML contradisser o que foi informado, **o XML vence** — já
aconteceu de o desdobro municipal "de cabeça" estar errado e o correto vir das próprias notas.

### A nota canário (quando não há homologação)
Para município que **não existe em homologação** (§10), o único teste possível é uma nota **real**:
valor mínimo, tomador conhecido, **uma só**. Se emitir, você aprendeu a verdade sobre IM/CNC/adesão
com a autoridade que importa. Ela é **documento fiscal**: cancele pelo caminho que o município aceita
(direto ou por pedido de análise) e **registre** o que foi feito. Antes de qualquer canário, valide
a DPS localmente e compare-a **campo a campo** com uma nota antiga do mesmo contribuinte — o canário
é para confirmar o que você já acha que sabe, não para descobrir no escuro.

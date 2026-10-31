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

> **O certificado do SERVIDOR é conferido.** Os dois endpoints da SEFIN usam cadeia pública
> (GlobalSign, emitida pelo SERPRO; o ADN usa Let's Encrypt) — medido em 31/10/2026. A lib confere
> por padrão desde a 1.2.0 (antes ia com `verify=False`, herdado da referência PHP). Só os
> endpoints próprios de município ficam sem conferência por padrão: o de Catanduva é um IP cru.
> Se a cadeia mudar um dia, `SefinClient(verificar_servidor="caminho/do/ca-bundle.pem")`.

> ⚠️ **Homologação à frente da produção (31/10/2026).** Neste dia a homologação passou a recusar
> a DPS do leiaute atual com **E1235** — *"invalid child element 'cLocEmi' … expected
> 'cMotivoEmisTI, finNFSe'"*: o esquema de lá já espera esses campos no `infDPS`, antes do
> `cLocEmi`. A produção segue aceitando a DPS atual. É o aviso de que o leiaute vai mudar; até a
> lib acompanhar, a emissão em homologação fica bloqueada (consulta, eventos e DF-e funcionam).

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
- **Não Optante (`opSimpNac=1`)** usa `indTotTrib` — ou, quando configurado, o **`pTotTrib`**
  (percentuais federal/estadual/municipal, §14); só o **ME/EPP (3)** usa `pTotTribSN`.
- **`regApTribSN` é exclusivo do ME/EPP (3).** Para o Não Optante **e** para o MEI ele é
  **proibido** (**E0162**). O motor o omite por `opSimpNac`, sem depender da config (o default
  `regApTribSN=1` da dataclass não vaza para quem não é ME/EPP).
- O motor implementa esse chaveamento em `dps.py` (`regTrib` e `totTrib`) e o validador só exige
  `pTotTribSN` quando `opSimpNac==3`. Regressão: `test_mei_usa_indtottrib_e_omite_regaptribsn`.

---

## 4. ★ Tabela de erros do SEFIN (a jornada — todos resolvidos)

A regra de cada erro é **fiscal**, vale para qualquer linguagem. A "Solução" descreve o que mandar
(ou deixar de mandar) na DPS.

| Código | Sintoma | Causa | Solução |
|---|---|---|---|
| **E0008** *(causa 1)* | data de emissão "posterior ao processamento", em **toda** nota | máquina em UTC × SEFIN em Brasília (erro de 3h) | fixar fuso **America/Sao_Paulo** antes de gerar `dhEmi` |
| **E0008** *(causa 2)* | idem, mas **intermitente** — a mesma nota passa no reenvio | **margem zero**: `dhEmi` era o PISO do segundo (`date('c')` / `.replace(microsecond=0)`), e o pool do SEFIN corre de ~0 a ~1s ATRÁS do nosso. Provado em 30/08/2026 (48 notas de um prestador numa noite): `dhProc` caiu no MESMO segundo do `dhEmi` em 12 de 16 notas; 1 delas estourou | recuar `dhEmi` de **`MARGEM_E0008_S` (5s)**, com trava de meia-noite p/ não trocar a competência — `relogio.recuar()` |
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
| **E0162** | "não é permitido ao não optante e ao MEI preencherem o regime de apuração" | `regApTribSN` numa DPS de `opSimpNac` 1 ou 2 | `regApTribSN` **só** para ME/EPP (`opSimpNac=3`) — o motor omite (§3) |
| **E0204** | "CNPJ ou CPF do tomador não foi informado, mas existe indicação de retenção do ISSQN" | `tpRetISSQN=2` sem `<toma>` identificado | retenção pelo tomador exige o tomador com documento (§15) |
| **E0237** | "o endereço nacional do tomador deve ser informado quando o ISSQN for retido pelo tomador" | `tpRetISSQN=2` com o `<end>` do tomador ausente (ou omitido por estar incompleto) | endereço nacional **completo** do tomador (§7, §15) |
| **E0583** · **E0588** · **E0580** | retenção do ISSQN não permitida | `tpRetISSQN` 2/3 com prestador **MEI** (E0583), com **regime especial** `regEspTrib≠0` (E0588), ou com `tribISSQN` imune/exportação/não incidência (E0580) | sem retenção (`tpRetISSQN=1`) nesses casos (§15) |
| **E0617** | "não é permitido informar alíquota" (não optante) | `pAliq` numa DPS de **Não Optante** em município com convênio **ativo** — a alíquota é parametrizada pelo município e o SEFIN a aplica | **omitir `pAliq`** (§15) |
| **E0698** | "se o CST for diferente de 00, 08 ou 09, o tipo de retenção do PIS/COFINS deve ser informado" | `piscofins/CST` tributável sem `tpRetPisCofins` | informar `tpRetPisCofins` (§12) |
| **E0316** | "código da lista NBS inexistente" | `cNBS` fora da tabela NBS (Anexo B do Manual Integrado) | usar o Item da NBS que o portal oferece para aquele serviço (§14) |

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
- **A DPS já existe na SEFIN** (o `HEAD /dps/{id}` volta 200): ou é a MESMA nota, que saiu e a
  resposta se perdeu, ou o contador está atrasado e o número é de OUTRA nota. A lib busca o XML
  pela chave e compara **valor + documento do tomador** (a descrição fica fora — reescrevê-la num
  reenvio não faz dela outra nota). Mesma nota → `ja_emitida` com o XML; outra nota → pula o
  número; sem XML para conferir → `ja_emitida` (o ambíguo conta como feito). O contador avança
  nos três casos. Até a 1.1.0 ele não avançava, e toda emissão seguinte caía na mesma DPS.
  Quem passa o `numero=` explícito controla a numeração: a lib só recupera a nota.

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

## 8. IBS/CBS (reforma tributária)

O **leiaute** da DPS já está em **1.01** (RTC — NT 004 v2.0 / NT 007); ver `VERSAO_DPS` em `dps.py`.
O grupo `IBSCBS` é **opcional no schema** (`minOccurs=0`) e o montador o emite **só quando a
config pede** (`servico.ibscbs`, §14). Sem o bloco, a DPS sai exatamente como antes.

### O que a DPS leva — e o que ela NÃO leva

A DPS carrega só a **classificação** da operação; **nenhum valor** de IBS/CBS. Base de cálculo,
alíquotas e valores são **calculados pelo SEFIN** e voltam na NFS-e (`infNFSe/IBSCBS`). Medido numa
NFS-e de Regime Regular autorizada em produção (cStat 100, competência 10/2026): serviço de
R$ 180,00 com ISS de 3% → a NFS-e trouxe `vBC` 174,60 (o serviço **menos o ISSQN**), IBS UF 0,10%
(R$ 0,17), IBS municipal 0% e CBS 0,90% (R$ 1,57) — as alíquotas de teste de 2026.

Ordem do XSD (`TCRTCInfoIBSCBS`), depois de `<valores>`, como último filho do `infDPS`:

```
<IBSCBS>
  finNFSe        1      0 = NFS-e regular (única opção do leiaute)
  indFinal       0-1    operação de uso ou consumo pessoal (art. 57 da LC 214): 0 = Não, 1 = Sim
  cIndOp         1      código indicador da operação (tabela "INDOP", Anexo C) — 6 dígitos
  (tpOper, gRefNFSe, tpEnteGov)   0-1   não cobertos
  indDest        1      0 = o destinatário é o próprio tomador/adquirente; 1 = outro (exige <dest>)
  (dest, imovel)                  0-1   não cobertos
  <valores><trib><gIBSCBS>
    CST          1      situação tributária do IBS/CBS — 3 dígitos (ex.: 000 = tributação integral)
    cClassTrib   1      classificação tributária — 6 dígitos (ex.: 000001)
  </gIBSCBS></trib></valores>
</IBSCBS>
```

O portal do governo (EmissorWeb), para o caso comum (destinatário = adquirente, compra **não**
governamental), emite exatamente esse mínimo: `finNFSe 0`, `indFinal 0`, `cIndOp`, `indDest 0` e
`gIBSCBS` com `CST` + `cClassTrib`. É o que este montador reproduz.

**Cronograma** (Ato Conjunto RFB/CGIBS nº 4, de 30/07/2026 — contado pelo **fato gerador**, que na
NFS-e é o `dCompet`, não o dia da emissão):

| Quem | Grupo IBS/CBS na NFS-e |
|---|---|
| **Regime Regular** (Lucro Presumido/Real), serviços da lista da LC 116 em geral | obrigatório desde **01/10/2026** |
| Regime Regular — software/dados/streaming (1.03, 1.05, 1.09), transporte municipal (16.01), plataformas digitais, condomínio, locação e serviços fora da LC 116 | obrigatório desde **01/12/2026** |
| **Simples Nacional** (qualquer serviço) | obrigatório a partir de **01/01/2027** (Ato Conjunto nº 4, art. 1º, § 1º) |

⚠️ **Obrigatório não é o mesmo que rejeitado:** até 31/12/2026 o SEFIN **autoriza** a DPS sem o
grupo (medido em 01/10/2026: nota de um optante do Simples, competência 01/10/2026, autorizada sem o
grupo). A nota passa e fica em **desconformidade** — teste que passa não prova conformidade. Para o
Regime Regular isso custa dinheiro: a dispensa do recolhimento de 2026 é condicionada à obrigação
acessória (art. 348, § 1º). A data de 03/08/2026, citada em versões antigas deste
documento, vale para **NF-e/NFC-e**, não para a NFS-e.

Para o **Simples**, emite-se **sem** o grupo **até 31/12/2026** (sem `servico.ibscbs`, nada muda).
Para o **Regime Regular**, configure o grupo (§14) — ele já é obrigatório.

Ainda **não cobertos** (o validador recusa a config em vez de emitir pela metade): destinatário
diferente do adquirente (`indDest=1` → grupo `<dest>`), compra governamental (`tpEnteGov`), nota
de ajuste/referência (`gRefNFSe`), imóvel, redução/diferimento (`gTribRegular`, `gDif`) e crédito
presumido (`cCredPres`).

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
> E o contrário também acontece: um prestador cujas notas de **produção** saem **sem** IM (DPS
> montada pelo próprio portal do governo, autorizada) levou **E0116** em homologação sem ela — e
> foi autorizado lá só com a IM antiga do sistema da prefeitura. O CNC de homologação não é o de
> produção.
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

### `tpRetPisCofins` — o tipo de retenção (NT 007)

Depois do `CST`, o `piscofins` aceita `tpRetPisCofins`. A NT 007 ampliou o domínio para **0 a 9**
(`0` = PIS/COFINS/CSLL não retidos, `1` = PIS/COFINS retidos, `3` = PIS/COFINS/CSLL retidos…); a
revisão antiga do XSD só tinha `1`/`2`. O SEFIN de produção aceita a nova (nota do Regime Regular
autorizada com `CST 00` + `tpRetPisCofins 0`, emitida pelo próprio portal do governo).

- **Obrigatório** quando o CST é tributável — qualquer um **fora** de `00`, `08` e `09` (**E0698**).
- Opcional nos outros; o portal manda `0` junto do `CST 00` no Regime Regular.

Configurável em `servico.tributos.tpRetPisCofins` (um dígito). Sem ele, o elemento é omitido e a
DPS do Simples sai idêntica à de sempre.

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

---

## 14. ★ Regime Regular (Não Optante — Lucro Presumido/Real): a DPS é outra

O prestador **fora do Simples** (`opSimpNac=1`) não monta a DPS do ME/EPP com um número trocado.
Cinco pontos mudam, e cada um custa uma rejeição ou uma nota em desconformidade. Fonte da verdade:
uma NFS-e de Lucro Presumido **emitida pelo próprio portal do governo** (EmissorWeb) e autorizada
em produção (cStat 100) — o mesmo método do §13.

| Elemento | ME/EPP (`opSimpNac=3`) | **Não Optante (`opSimpNac=1`)** |
|---|---|---|
| `regTrib/regApTribSN` | presente | **omitido** — informar dá **E0162** (§3) |
| `prest/IM` | conforme o CNC (§10) | conforme o CNC (§10) — o portal omitiu num município que tinha IM no sistema antigo da prefeitura, e a SEFIN aceitou |
| `cServ/cNBS` | opcional | o portal manda (o **Item da NBS** é obrigatório na tela do Regime Regular) |
| `tribMun/pAliq` | ver §15 | **omitido** em município com convênio ativo (**E0617**): a alíquota vem da parametrização municipal |
| `tribFed/piscofins` | `CST` (default `08`, §12) | `CST 00` + `tpRetPisCofins 0` no portal (§12) |
| `totTrib` | `pTotTribSN` | **`pTotTrib`** (federal/estadual/municipal) — ou `indTotTrib` |
| grupo `IBSCBS` | a partir de 01/01/2027 | **obrigatório** desde 01/10/2026 (§8) |

### `totTrib/pTotTrib` — o valor aproximado dos tributos (Lei 12.741/2012)

O Não Optante pode declarar `indTotTrib=0` (não informar), mas o portal emite o **percentual
aproximado** em três parcelas, cada uma de 0 a 100% (**E0706–E0708**):

```xml
<totTrib><pTotTrib>
  <pTotTribFed>11.33</pTotTribFed>   <!-- PIS 0,65 + COFINS 3,00 + IRPJ 4,80 + CSLL 2,88 -->
  <pTotTribEst>0.00</pTotTribEst>
  <pTotTribMun>3.00</pTotTribMun>    <!-- a alíquota do ISS do serviço -->
</pTotTrib></totTrib>
```

O exemplo é o de um serviço no **Lucro Presumido** (presunção de 32%: IRPJ 15% × 32% = 4,80%;
CSLL 9% × 32% = 2,88%; PIS/COFINS cumulativos 0,65% + 3%). Os números são da **contabilidade** do
prestador — não há fórmula universal: atividade com presunção diferente, adicional de IRPJ ou ISS
de outra alíquota mudam a soma. Configurável em `servico.tributos.pTotTrib` (as três chaves do
XSD). Esta biblioteca só o aceita para o Não Optante: para o ME/EPP o caminho é o `pTotTribSN` e
o MEI é isento (Decreto 8.264/2014, §3).

### `cNBS` — o Item da NBS

`serv/cServ/cNBS` (9 dígitos, tabela NBS do Anexo B do Manual Integrado), **depois** do `xDescServ`.
É opcional no XSD que o SEFIN aplica em produção (DPS do Simples sem ele é autorizada), mas o
portal o exige do Regime Regular e ele classifica o serviço para o IBS/CBS. Código fora da tabela
dá **E0316**. Configurável em `servico.cNBS`; vazio omite o elemento.

### O grupo IBS/CBS

Configurável em `servico.ibscbs` (§8): `cIndOp`, `CST`, `cClassTrib` (obrigatórios no bloco),
`indFinal` (opcional), `finNFSe` e `indDest` (só `0` é suportado). O exemplo do portal para
manutenção de máquinas de um adquirente PJ: `cIndOp 050101`, `CST 000`, `cClassTrib 000001`,
`indFinal 0`, `indDest 0`. Os códigos são **decisão da contabilidade**, por operação — não copie
de outro prestador.

---

## 15. ★ ISS retido pelo tomador (`tpRetISSQN=2`)

A retenção é propriedade da **operação** (de quem é o tomador), não do prestador: o mesmo prestador
emite notas retidas para os tomadores que a lei municipal obriga a reter e não retidas para os
outros. A config desta biblioteca é **por prestador** — quem emite para os dois tipos de tomador
monta a config da nota com `servico.tributos.tpRetISSQN = 2` só naquela emissão.

`tpRetISSQN`: `1` = não retido (default) · `2` = retido pelo tomador · `3` = retido pelo
intermediário (exige o grupo `<interm>`, **não coberto**).

### O que a retenção exige — e proíbe

| Regra | E-code |
|---|---|
| o tomador tem de estar **identificado** (CPF/CNPJ) | **E0204** |
| o **endereço nacional** do tomador é **obrigatório** (o `<end>` deixa de ser opcional) | **E0237** |
| MEI não sofre retenção | **E0583** |
| prestador com regime especial (`regEspTrib≠0`) não sofre retenção | **E0588** |
| serviço imune, exportado ou sem incidência (`tribISSQN` 2/3/4) não tem retenção | **E0580** |

⚠️ O E0237 é o que pega de surpresa: o `<end>` do tomador é bloco **atômico** (§7) — se faltar um
campo, ele some inteiro, e a nota que sairia "sem o endereço" com ISS não retido passa a ser
**rejeitada** com retenção. O validador desta biblioteca confere os dois (E0204/E0237) antes do
envio.

### `pAliq` — quando a alíquota vai na DPS

Quem decide é o regime, o convênio do município de incidência e a retenção:

| Prestador | Convênio do município | Retenção | `pAliq` |
|---|---|---|---|
| Não Optante (`opSimpNac=1`) | **ativo** | qualquer | **proibido** (E0617) — o SEFIN aplica a alíquota parametrizada |
| Não Optante | não ativo (e `regEspTrib=0`) | qualquer | obrigatório (E0619) |
| ME/EPP, ISS pelo SN (`regApTribSN=1`) | qualquer | **sim** (`tpRetISSQN` 2/3) | **obrigatório** (E0621/E0628), mínimo 1,8% |
| ME/EPP, ISS pelo SN | qualquer | não | proibido (E0625/E0631) |
| ME/EPP, ISS fora do SN (`regApTribSN` 2/3) | ativo | — | proibido (E0635) |
| ME/EPP, ISS fora do SN | não ativo | — | obrigatório (E0640) |

Esta biblioteca **não emite `pAliq`**: ela cobre o Não Optante em município com convênio ativo
(retido ou não) e o ME/EPP sem retenção. O ME/EPP com ISS **retido** precisaria da alíquota — o
validador recusa essa config (E0621) em vez de deixar a DPS ir para a rejeição.

### Na NFS-e

Medido em homologação (Regime Regular, serviço de R$ 100,00, ISS 3%, mesma DPS com
`tpRetISSQN` 1 e 2): com a retenção a NFS-e devolve `vTotalRet` = o ISSQN (3,00) e `vLiq` =
97,00 — o valor que o prestador recebe; sem ela, `vTotalRet` some e `vLiq` = 100,00. A base do
IBS/CBS foi 97,00 **nos dois casos** (o serviço menos o ISSQN, retido ou não — §8). O DANFSe
imprime "Retenção do ISSQN: Retido pelo Tomador".

---

## 16. ★ Cancelamento — direto (e101101) × análise fiscal (e101103)

O cancelamento é um **evento**: um `pedRegEvento` assinado no `infPedReg` (mesmo perfil da DPS:
RSA-SHA1, `<Signature>` depois do nó assinado) e enviado em `gzip+base64` no campo
`pedidoRegistroEventoXmlGZipB64` de `POST /nfse/{chave}/eventos`.

| Modo | Evento | Quando | Efeito |
|---|---|---|---|
| `direto` | e101101 | o município aceita o cancelamento pelo contribuinte | nota cancelada na hora |
| `analise` | e101103 | o município **não** aceita o direto (ele volta **E0823**) | nota "em análise" até o fisco municipal deferir |

O que muda de um município para outro é só o modo — e não há como saber antes de tentar: o
direto recusado com E0823 diz que ali é análise. Mesmo pelo portal web é assim.

**A estrutura** (validada em homologação e idêntica, byte a byte, à da implementação de referência
que cancela em produção): `Id = "PRE" + chave + tipo do evento`; `tpAmb` → `verAplic` →
`dhEvento` → `CNPJAutor` (ou `CPFAutor`) → `chNFSe` → `e1011xx { xDesc, cMotivo, xMotivo }`.

- ☠️ **`xDesc` é enumeração e a SEFIN exige o texto ACENTUADO.** O XSD publicado (v1.01) lista
  `Solicitacao de Analise Fiscal…` sem acento; enviado assim volta **E1235**. Aceito:
  `Cancelamento de NFS-e` e `Solicitação de Análise Fiscal para Cancelamento de NFS-e`.
- `cMotivo`: **1** Erro na Emissão · **2** Serviço não Prestado · **9** Outros.
- `xMotivo` (justificativa): **15 a 200 caracteres**.
- `dhEvento` leva o mesmo recuo do `dhEmi` (§4, E0008).
- Cancelar de novo uma nota já cancelada volta **E0840** ("o evento de Cancelamento já está
  vinculado à NFS-e") — medido em homologação.
- **Substituição** é outro evento (e105102, com motivos próprios) e ainda não está na lib.

## 17. Consulta da NFS-e pela chave

`GET /nfse/{chave}` devolve `nfseXmlGZipB64` — o mesmo XML da emissão, de onde sai o DANFSe.
404 = a chave não existe. Qualquer outro status é "não deu para saber", **nunca** "não existe".
É o que permite à nota recuperada (`ja_emitida`) chegar com o XML, e não só com a chave.

O XML da NFS-e **não traz `<chNFSe>`**: a chave mora no `Id` do `infNFSe` (`NFS` + 50 posições).
E o `nNFSe` está dentro da própria chave (posições 24 a 36), o que serve de reserva quando o XML
não veio. Layout: cMun 7 · tpAmb 1 · tpInsc 1 · CNPJ/CPF 14 · nNFSe 13 · AAMM 4 · código 9 · DV 1
(conferido contra 325 NFS-e autorizadas).

## 18. Distribuição DF-e — a caixa postal do CNPJ (ADN)

`GET https://adn.nfse.gov.br/contribuintes/DFe/{NSU}?cnpjConsulta={CNPJ}&lote=true`, com o mesmo
certificado (homologação: `adn.producaorestrita.nfse.gov.br`). Traz tudo o que está ligado ao
CNPJ: as notas que ele **emitiu**, as que **recebeu** como tomador e os **eventos**.

- Resposta: `StatusProcessamento` + `LoteDFe[]`; cada item tem `NSU`, `TipoDocumento` (`NFSE` |
  `EVENTO`), `ChaveAcesso`, `TipoEvento` (texto, ex. `CANCELAMENTO`), `DataHoraGeracao` e
  `ArquivoXml` (o XML em `gzip+base64` — com `lote=true` ele já vem embutido).
- ~50 itens por página. A próxima página parte do **maior NSU recebido**; guarde-o para a
  sincronização seguinte (o NSU só cresce).
- O fim vem como `StatusProcessamento` de "nenhum documento" — e a grafia muda: já veio
  `NenhumDocumentoLocalizado` e, em 31/10/2026, `NENHUM_DOCUMENTO_LOCALIZADO`. Compare sem caixa
  nem `_`. O HTTP pode ser 404 nesse caso, com o corpo JSON normal.
- **Limite de taxa (HTTP 429):** pausa de ~1 s entre páginas e, no 429, a MESMA página de novo
  com espera crescente (3, 6, 9… s) — é o que a implementação de referência faz em produção para
  baixar caixas de centenas de notas.
- **Emitida × recebida:** o XML não diz de que lado o CNPJ está — compare o CNPJ do `<prest>` da
  DPS (sem ele, o do `<emit>`) com o do certificado.


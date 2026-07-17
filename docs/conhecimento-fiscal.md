# Conhecimento fiscal — NFS-e Nacional (DPS) + DANFSe

> Este documento é o **coração** do projeto: o conhecimento fiscal ganho a sangue emitindo notas
> reais no Sistema Nacional NFS-e. A implementação Python muda de linguagem, mas **estas regras
> não mudam** — são do SEFIN, não da linguagem. Originado de uma implementação de referência em PHP
> (privada) que já emite em produção; aqui está destilado e independente de lib.

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
| Inscrição Municipal | só se o município exigir |

### Pego automaticamente pelo SEFIN (NÃO enviar)
- **Nome e endereço do prestador** (do cadastro nacional) → enviar dá **E0128/E0121**.
- **Número fiscal `nNFSe`** — o SEFIN atribui, continuando a sequência real do prestador (§5).

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
| **E0712** | "ME/EPP: `indTotTrib` não pode ser informado" | Simples não usa `indTotTrib` | usar **`totTrib/pTotTribSN`** (% efetiva do SN) |
| **E1235** | "trib sem `totTrib`" | `totTrib` é obrigatório | sempre enviar `totTrib` (`pTotTribSN` p/ Simples; `indTotTrib` p/ não optante) |
| **E1235** | "Pattern TSCodTribNac" | `cTribNac` com 9 díg | `cTribNac` é **6 díg**; o desdobro vai em `cTribMun` |
| **E1235** | "Falha no esquema (verAplic)" | `verAplic` > 20 chars | **`verAplic` ≤ 20** caracteres |
| **E1235** | "`toma` incompleto (expected CAEPF, IM, xNome)" | tomador só com CPF/CNPJ | tomador identificado **EXIGE nome** (`xNome`); ver §7 |

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

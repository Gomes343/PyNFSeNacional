<div align="center">

# PyNFSeNacional

**Emissão de NFS-e pela API do Sistema Nacional (SEFIN) e geração do DANFSe — em Python.**

Feito por um contador da **[GT Contabilidade](https://gtcontabilidade.com)**, para contadores e
desenvolvedores que precisam emitir nota fiscal de serviço no **padrão nacional** sem depender de
robô de navegador nem da API de PDF do governo.

[![CI](https://github.com/Gomes343/PyNFSeNacional/actions/workflows/ci.yml/badge.svg)](https://github.com/Gomes343/PyNFSeNacional/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/PyNFSeNacionalGT?color=blue&cacheSeconds=3600)](https://pypi.org/project/PyNFSeNacionalGT/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Ruff](https://img.shields.io/badge/lint-ruff-261230)](https://github.com/astral-sh/ruff)
[![Checked: mypy](https://img.shields.io/badge/types-mypy%20strict-blue)](https://mypy-lang.org/)
[![Status](https://img.shields.io/badge/status-lan%C3%A7ado-brightgreen)](CHANGELOG.md)

</div>

> ✅ **Lançado — v1.0.** Em **produção real desde junho de 2026**: é o motor que emite as NFS-e de um
> escritório de contabilidade, mês após mês, para prestadores de vários municípios — **centenas de
> notas autorizadas** pelo SEFIN Nacional. O pipeline completo (`config → certificado → DPS →
> assinatura → transporte mTLS → DANFSe`) é validado **byte a byte** contra uma implementação de
> referência e coberto por testes. A responsabilidade pela nota é sempre do emitente: **valide cada
> emissão**.

---

## Por que existe

Com o **Sistema Nacional NFS-e** virando o padrão do país — e a reforma tributária (IBS/CBS) passando
por ele —, todo escritório de contabilidade precisa emitir NFS-e pelo padrão nacional. O ecossistema **PHP** já
tem bibliotecas maduras para isso; o **Python**, não — falta uma solução turnkey, ponta a ponta. Este
projeto preenche essa lacuna, **integrando** o que o ecossistema fiscal Python já tem de melhor e
adicionando o que faltava (o transporte ao SEFIN nacional + o acabamento).

### Duas confusões que este projeto já resolve

1. **Existem duas APIs do governo.** A de **emissão** (SEFIN Nacional) recebe a **DPS** assinada e
   devolve a **NFS-e** — é viva e é o futuro. A de **geração de PDF/DANFSe** (ADN) está sendo
   **descontinuada** (NT-008/2026). Por isso, aqui o **DANFSe é gerado localmente**.
2. **`ambGer` não é ambiente.** O indicador Produção/Homologação é o `tpAmb`, **não** o `ambGer`
   (toda nota nacional tem `ambGer=2`). Confundir os dois marca nota de produção como "sem validade".

---

## ✨ Destaques

- 🧾 **Emite NFS-e pela API oficial** (SEFIN Nacional) com certificado A1 — sem robô de navegador.
- 🖨️ **DANFSe gerado localmente** (PDF), antecipando o fim da API de PDF do governo.
- 🔐 **Assinatura XMLDSIG** por biblioteca madura (`erpbrasil.assinatura`), validada byte a byte.
- ✅ **Validação fiscal antes de enviar** — pega E0312/E0712/E1235… e CPF/CNPJ (mód-11) localmente.
- 🔁 **Idempotência nativa** (`verificarDps`) — não duplica nota num reenvio.
- 🧩 **Núcleo enxuto e MIT-limpo**; a geração de PDF é uma dependência **opcional**.
- 🐍 Tipado (`mypy --strict`), testado (incl. *golden* contra a referência) e com CLI turnkey.

---

## 📦 Instalação

```bash
# núcleo: emite a NFS-e (sem gerar PDF)
pip install PyNFSeNacionalGT

# + geração local do DANFSe (PDF) — dependência opcional
pip install "PyNFSeNacionalGT[danfse]"
```

> Requer **Python 3.10+**. No PyPI o pacote se chama **`PyNFSeNacionalGT`** (o nome `PyNFSeNacional`
> esbarra na proteção do PyPI por semelhança com outro projeto); o **import continua `pynfsenacional`**.
> Pin recomendado: **`PyNFSeNacionalGT>=0.5.0`** — a v0.1.0 tem o bug de ordem da `<IM>` (corrigido
> na 0.2.0), a 0.3.0 traz o leiaute RTC 1.01, a 0.4.0 o MEI e o CNPJ alfanumérico, e a 0.5.0 a
> Inscrição Municipal opcional de verdade (§10 do conhecimento fiscal).

---

## 🚀 Quickstart

### Em Python

```python
from pynfsenacional import Emissor

emissor = Emissor("config/cliente.json")          # certificado A1 + dados do prestador

nota = emissor.emitir(                              # monta DPS → assina → envia ao SEFIN
    valor=150.00,
    descricao="Sessão de psicoterapia",
    tomador={"cpf_cnpj": "00000000000", "nome": "Fulano de Tal"},
)

print(nota.emitida, nota.numero_nfse, nota.chave_acesso)
nota.danfse("nota.pdf")                             # gera o PDF do DANFSe localmente
```

### Pela linha de comando

```bash
nfse-nacional emitir config/cliente.json \
    --valor 150,00 --descricao "Sessão de psicoterapia" \
    --tomador-doc 00000000000 --tomador-nome "Fulano de Tal" \
    --ambiente homologacao \
    --pdf nota.pdf
```

| Saída | Significado |
|---|---|
| `✅ emitida — nNFSe 13 · chave 3304…` | nota emitida; o `nNFSe` é atribuído pelo SEFIN |
| `❌ não emitida: [E0312] …` | rejeitada pelo SEFIN, com o código do erro |
| `❌ config inválida: …` | barrada **antes** do envio pela validação local |

> Os `00000000000` acima são **placeholders**: o tomador precisa de CPF/CNPJ **válido** (a lib
> confere o dígito mód-11 localmente). Sem tomador, a nota sai como **consumidor final** (omite `<toma>`).

> **Operação:** o `nDPS` é um contador **interno** por prestador+ambiente, persistido em
> `out/numero_<id>_<ambiente>.txt` — quem atribui o `nNFSe` é o SEFIN. Reenviar a mesma DPS é
> **idempotente** (`verificarDps`): não duplica. Para acompanhar o passo a passo, rode
> `nfse-nacional -v emitir …` (o `-v` vem **antes** do subcomando).

---

## 🔧 Configuração (passo a passo)

Cada prestador é descrito por um **JSON puro**. Comece copiando o exemplo anotado:

- 📄 [`examples/config-exemplo.json`](examples/config-exemplo.json) — pronto para copiar (JSON puro).
- 📝 [`examples/config-exemplo.jsonc`](examples/config-exemplo.jsonc) — o mesmo, **comentado** campo a campo.
- 📚 Schema completo em [`docs/conhecimento-fiscal.md`](docs/conhecimento-fiscal.md) (§3).

```jsonc
{
  "id": "exemplo",
  "nome_cliente": "EMPRESA EXEMPLO LTDA",
  "ambiente": "homologacao",            // homologacao (teste) | producao (nota real)

  "certificado": {                      // ★ certificado A1 do PRÓPRIO prestador (.pfx)
    "path": "certs/exemplo.pfx",        //   NUNCA versionar — fica fora do git
    "senha": "0000"
  },

  "prestador": {
    "cnpj": "00000000000000",           // ★ 14 dígitos
    "codigo_municipio": "0000000",      // ★ IBGE 7 díg do município do emitente
    "inscricao_municipal": null,        //   OPCIONAL — quem decide é o CNC, POR CNPJ (E0116 ×
                                        //   E0120). Sem IM no CNC: deixe null. Nunca "de enfeite"
    "regime": {                         // ★ regime tributário
      "opSimpNac": 3,                   //   1=Não Optante (roadmap) · 2=MEI · 3=Optante ME/EPP
      "regApTribSN": 1,
      "regEspTrib": 0
    }
    // nome/endereço do prestador NÃO entram aqui: o SEFIN puxa do cadastro (E0128/E0121)
  },

  "servico": {
    "codigo_municipio_prestacao": "0000000",  // ★ IBGE do local da prestação
    "cTribNac": "041601",               // ★ Código de Tributação NACIONAL (6 díg, LC116)
    "cTribMun": "001",                  //   desdobro municipal — obrigatório onde o município
                                        //   usa desdobro (senão E0312); município sem desdobro
                                        //   REJEITA o campo (E0315): deixe "" e ele é omitido
    "descricao_padrao": "Serviço Prestado",
    "tributos": {
      "pTotTribSN": "6.00",             // ★ se Simples ME/EPP: % efetiva do Simples Nacional
      "piscofins_cst": "08"             //   CST do PIS/COFINS: "08"=sem incidência (default),
    }                                   //   "00"=nenhum. Confira no XML do próprio contribuinte
  }
}
```

### O que cada prestador precisa fornecer

| Dado | Onde obter |
|---|---|
| **Certificado A1 (.pfx) + senha** | do próprio prestador (anuência); renove antes de vencer |
| **CNPJ** | cadastro |
| **Código do município (IBGE)** | município de atuação do prestador |
| **Regime** (`opSimpNac`/`regApTribSN`) | contabilidade (é Simples? MEI ou ME/EPP?) |
| **`cTribNac`** (6 díg) | item da LC116 da atividade (mesmo código do portal) |
| **`cTribMun`** (desdobro) | o que o município administra p/ aquele `cTribNac` (alguns não usam) |
| **Inscrição Municipal** | **o CNC do município, por CNPJ** — não é "por cidade" ([§10](docs/conhecimento-fiscal.md)) |
| **`pTotTribSN`** (% Simples) | alíquota efetiva do Simples (contabilidade) |

> 🔒 **Nada sensível vai para o git.** O `.pfx`, as configs reais (`config/`) e os XML/PDF de notas são
> ignorados por padrão (ver [`.gitignore`](.gitignore)). Os dados de exemplo são **fictícios**.

---

## 🧩 Como funciona

Este pacote **integra** as libs maduras do ecossistema fiscal Python e escreve só o que faltava
(o transporte ao SEFIN nacional + o acabamento). Ver [`docs/roadmap.md`](docs/roadmap.md).

```
config (JSON)  →  montar DPS (XML)  →  assinar (XMLDSIG)  →  gzip+base64 → POST /nfse (mTLS)
                       │                     │                                    │
                    lxml            erpbrasil.assinatura                    SEFIN Nacional
                                                                                  │
                                                                            NFS-e (XML)
                                                                                  │
                                                                  render DANFSe local (PDF)
                                                                                  │
                                                                          BrazilFiscalReport
```

| Peça | Biblioteca | Módulo |
|---|---|---|
| Montar/serializar o XML da DPS | [`lxml`](https://lxml.de/) | `dps.py` |
| Assinatura digital XMLDSIG | [`erpbrasil.assinatura`](https://github.com/erpbrasil/erpbrasil.assinatura) | `assinatura.py` |
| Ler o certificado A1 `.pfx` | [`cryptography`](https://cryptography.io) | `certificado.py` |
| Transporte mTLS ao SEFIN | `requests` + `requests-pkcs12` + **código próprio** | `sefin.py` |
| Gerar o DANFSe (PDF) | [`BrazilFiscalReport`](https://github.com/Engenere/BrazilFiscalReport) | `danfse.py` |
| Validação fiscal + CLI | — | `config.py`, `cli.py` |

---

## 🗺️ Status e roadmap

✅ Implementado e validado · ⏳ próximo

- ✅ Config + validação fiscal (E-codes, CPF/CNPJ mód-11)
- ✅ Leitura do certificado A1 (`.pfx`)
- ✅ Montagem da DPS — **C14N idêntico, byte a byte, à referência PHP** (golden)
- ✅ Assinatura XMLDSIG (mesmo `DigestValue` do gabarito)
- ✅ Transporte mTLS + idempotência — **emissão real validada em homologação e produção**
- ✅ DANFSe local (PDF)
- ✅ CLI turnkey + logging
- ✅ Publicado no PyPI (`PyNFSeNacionalGT`)
- ✅ Tomador completo: `IM`, endereço, telefone e e-mail no `<toma>` (v0.2.0)
- ✅ Leiaute **RTC 1.01** da DPS (NT 004 v2.0 / NT 007) — alinhado à revisão oficial do XSD (defensivo p/ o endurecimento das validações RTC)
- ✅ **MEI** (`opSimpNac=2`) com DPS própria e **CNPJ alfanumérico** (NT 2025.001) — v0.4.0
- ✅ **Inscrição Municipal opcional** (regra do CNC por CNPJ) e `cTribMun` omitido onde o município não usa — v0.5.0
- ✅ **Margem anti-E0008** no `dhEmi` e **informações complementares** (`xInfComp`) — v1.0.0
- ⏳ Endurecimento a partir de mais emissões reais
- ⏳ Tomador estrangeiro / sem documento; não-optantes (Lucro Presumido/Real)
- ⏳ Grupo **IBS/CBS** na DPS — **próxima prioridade.** Obrigatório na NFS-e para o **Regime Regular**
  desde 01/10/2026 (sem rejeição até 31/12/2026) e para o **Simples Nacional a partir de 01/01/2027**
  (Ato Conjunto RFB/CGIBS nº 4/2026); **ainda não emitido**
- ⏳ Eventos (cancelamento e substituição)
- ⏳ DANFSe: exibir o **total aproximado de tributos** do Simples (`pTotTribSN`, Lei 12.741) — hoje sai como "—" (o `BrazilFiscalReport` não lê esse campo)

Detalhes em [`docs/roadmap.md`](docs/roadmap.md) e [`CHANGELOG.md`](CHANGELOG.md).

---

## 🧪 Desenvolvimento

```bash
git clone https://github.com/Gomes343/PyNFSeNacional.git
cd PyNFSeNacional
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # dev já inclui o extra [danfse]

pytest                          # testes (inclui o golden contra a referência)
ruff check .                    # lint
mypy                            # tipos (strict)
```

Como contribuir: [`CONTRIBUTING.md`](CONTRIBUTING.md). Reportar vulnerabilidades: [`SECURITY.md`](SECURITY.md).

---

## 🏛️ Origem

Esta biblioteca nasceu dentro da **[GT Contabilidade](https://gtcontabilidade.com)** — escritório
contábil que emite NFS-e pelo padrão nacional, mês após mês, para empresas espalhadas por municípios
com regras diferentes entre si. Cada regra de [`docs/conhecimento-fiscal.md`](docs/conhecimento-fiscal.md)
foi **paga com nota real**: emissão travada, mensagem críptica do SEFIN, distância entre o que a
documentação diz e o que o município de fato aceita.

Esse conhecimento é vantagem competitiva e poderia ter ficado guardado. A GT preferiu **publicá-lo
sob licença MIT** — a obrigatoriedade do Sistema Nacional chega para todo mundo ao mesmo tempo, e
ninguém deveria precisar pagar duas vezes pela mesma descoberta. O que está aqui é a **regra fiscal
destilada** e o código que a implementa; **nunca** dado de contribuinte.

---

## ⚖️ Aviso legal

Biblioteca para emissão de NFS-e. **Use por sua conta e risco e valide cada emissão** — a responsabilidade pela nota é sempre do contribuinte/emitente. **Não é um produto
fiscal homologado/certificado e não substitui orientação contábil.** Sem garantia de qualquer tipo
(ver [LICENSE](LICENSE)).

## 📄 Licença

**MIT** — ver [LICENSE](LICENSE). O núcleo usa só dependências permissivas. A geração do DANFSe
(opcional, `[danfse]`) usa a **BrazilFiscalReport** (LGPL-3.0), empregada **como dependência** — quem
só emite não a instala.

## 🙏 Créditos

Construído sobre o trabalho da comunidade fiscal Python brasileira — **Akretion/erpbrasil**
(`erpbrasil.assinatura`) e **Engenere** (`BrazilFiscalReport`).

Mantido pela **[GT Contabilidade](https://gtcontabilidade.com)**, que bancou as emissões reais em
que cada regra deste repositório foi descoberta e validada.

<div align="center">

# PyNFSeNacional

**Emissão de NFS-e pela API do Sistema Nacional (SEFIN) e geração do DANFSe — em Python.**

Feito por um contador, para contadores e desenvolvedores que precisam emitir nota fiscal de serviço
no **padrão nacional** sem depender de robô de navegador nem da API de PDF do governo.

[![CI](https://github.com/Gomes343/PyNFSeNacional/actions/workflows/ci.yml/badge.svg)](https://github.com/Gomes343/PyNFSeNacional/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/PyNFSeNacionalGT?color=blue)](https://pypi.org/project/PyNFSeNacionalGT/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Ruff](https://img.shields.io/badge/lint-ruff-261230)](https://github.com/astral-sh/ruff)
[![Checked: mypy](https://img.shields.io/badge/types-mypy%20strict-blue)](https://mypy-lang.org/)
[![Status](https://img.shields.io/badge/status-alpha-orange)]()

</div>

> ⚠️ **Status: alpha.** O pipeline está **completo e funciona ponta a ponta** — `config → certificado
> → DPS → assinatura → transporte mTLS → DANFSe` — e já **emitiu em homologação** contra o SEFIN
> Nacional. A montagem da DPS é validada **byte a byte** contra uma implementação de referência em PHP
> que já emite em produção. Ainda assim, é uma biblioteca de emissão de NFS-e em estágio inicial: **valide cada emissão**.

---

## Por que existe

Com a obrigatoriedade do **Sistema Nacional NFS-e** chegando para o Simples Nacional (~set/2026), todo
escritório de contabilidade vai precisar emitir NFS-e pelo padrão nacional. O ecossistema **PHP** já
tem bibliotecas maduras para isso; o **Python**, não — falta uma solução turnkey, ponta a ponta. Este
projeto preenche essa lacuna, **integrando** o que o ecossistema fiscal Python já tem de melhor e
adicionando o que faltava (o transporte ao SEFIN nacional + o acabamento).

### Duas confusões que este projeto já resolve

1. **Existem duas APIs do governo.** A de **emissão** (SEFIN Nacional) recebe a **DPS** assinada e
   devolve a **NFS-e** — é viva e é o futuro. A de **geração de PDF/DANFSe** (ADN) é **descontinuada
   em 01/07/2026** (NT-008/2026). Por isso, aqui o **DANFSe é gerado localmente**.
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
> Durante o alpha ainda não há release publicado — para testar agora, instale do código (ver
> [Desenvolvimento](#-desenvolvimento)).

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
    "regime": {                         // ★ regime tributário
      "opSimpNac": 3,                   //   1=Não Optante · 2=MEI · 3=Optante ME/EPP
      "regApTribSN": 1,
      "regEspTrib": 0
    }
    // nome/endereço do prestador NÃO entram aqui: o SEFIN puxa do cadastro (E0128/E0121)
  },

  "servico": {
    "codigo_municipio_prestacao": "0000000",  // ★ IBGE do local da prestação
    "cTribNac": "041601",               // ★ Código de Tributação NACIONAL (6 díg, LC116)
    "cTribMun": "001",                  // ★ desdobro municipal (sem ele → E0312)
    "descricao_padrao": "Serviço Prestado",
    "tributos": { "pTotTribSN": "6.00" }// ★ se Simples: % efetiva do Simples Nacional
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
| **`cTribMun`** (desdobro) | o que o município administra p/ aquele `cTribNac` |
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
- ✅ Transporte mTLS + idempotência — **emissão real validada em homologação**
- ✅ DANFSe local (PDF)
- ✅ CLI turnkey + logging
- ⏳ Endurecimento a partir de mais emissões reais; publicação no PyPI
- ⏳ Tomador estrangeiro / sem documento; não-optantes (Lucro Presumido/Real)
- ⏳ Eventos (cancelamento); IBS/CBS (reforma tributária)

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

## ⚖️ Aviso legal

Biblioteca para emissão de NFS-e, em estágio **alpha**. **Use por sua conta e risco e valide cada
emissão** — a responsabilidade pela nota é sempre do contribuinte/emitente. **Não é um produto
fiscal homologado/certificado e não substitui orientação contábil.** Sem garantia de qualquer tipo
(ver [LICENSE](LICENSE)).

## 📄 Licença

**MIT** — ver [LICENSE](LICENSE). O núcleo usa só dependências permissivas. A geração do DANFSe
(opcional, `[danfse]`) usa a **BrazilFiscalReport** (LGPL-3.0), empregada **como dependência** — quem
só emite não a instala.

## 🙏 Créditos

Construído sobre o trabalho da comunidade fiscal Python brasileira — **Akretion/erpbrasil**
(`erpbrasil.assinatura`) e **Engenere** (`BrazilFiscalReport`).

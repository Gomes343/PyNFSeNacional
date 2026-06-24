# CLAUDE.md — PyNFSeNacional

> Guia de desenvolvimento deste repositório. **Antes de qualquer tarefa, leia
> [`docs/conhecimento-fiscal.md`](docs/conhecimento-fiscal.md)** — é onde mora a regra fiscal
> (estrutura da DPS, E-codes, numeração, DANFSe). E o [`docs/roadmap.md`](docs/roadmap.md) para o
> escopo e a ordem de build.

## O que é

Pacote Python público (MIT) que emite **NFS-e pela API SEFIN Nacional** (DPS) e gera o **DANFSe
localmente**. Vai para GitHub/PyPI. Feito por um contador, para a comunidade que vai bater na
obrigatoriedade nacional (~set/2026).

## Origem

- Este projeto **porta para Python puro** o conhecimento de uma **implementação de referência em
  PHP** (privada, fora deste repositório) que já emite em produção.
- Essa referência serve de **gabarito**: ao montar/assinar a DPS aqui, a saída é comparada byte a
  byte com a dela (ver `tests/golden/` e o roadmap), desriscando o ponto mais delicado
  (canonicalização XMLDSIG). O mantenedor aponta a referência via env `NFSE_PHP_REF` só ao
  regenerar o gabarito; o CI usa o XML já versionado e não precisa dela.
- Este repo é **autocontido e público** — **nada** de certificado, config real ou segredo entra no
  git (ver `.gitignore`). Dados de exemplo são fictícios.

## Princípio central: integrar, não reinventar

Não reimplementar criptografia. Cada peça tem uma lib madura do ecossistema fiscal Python; nós
costuramos e escrevemos só o que falta (transporte ao SEFIN + acabamento). Mapa no roadmap.

| Peça | Lib | Módulo |
|---|---|---|
| Montar/serializar XML da DPS | `lxml` | `dps.py` |
| Assinar XMLDSIG | `erpbrasil.assinatura` | `assinatura.py` |
| Ler `.pfx` A1 | `cryptography` | `certificado.py` |
| Transporte mTLS SEFIN | `requests` + próprio | `sefin.py` |
| DANFSe (PDF) | `BrazilFiscalReport` | `danfse.py` |
| Orquestração + CLI | — | `emissor.py`, `cli.py` |

## Estrutura

```
src/pynfsenacional/  # o pacote (config/cert/dps/assinatura/sefin/danfse/cli — pipeline completo)
docs/                # conhecimento-fiscal.md (regra) + roadmap.md (plano)
examples/            # config-exemplo.jsonc (fictício) + emitir_exemplo.py
tests/               # smoke + (futuro) testes de DPS/assinatura contra gabarito
```

## Como desenvolver

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                     # smoke
ruff check .               # lint
```

## Estado atual

**Alpha — pipeline completo.** Todas as peças estão implementadas; `Emissor.emitir()` roda
ponta a ponta: **validar → montar DPS → assinar → transporte mTLS → Nota** (+ `nota.danfse()`).

- `config.py` — dataclasses + `validar()` (E-codes) + loader tolerante. ✅
- `certificado.py` — leitura do `.pfx` via `cryptography` (+ fallback cifra legada §9). ✅
- `dps.py` — `montar_dps`/`id_dps`; o C14N do `infDPS` bate **byte-a-byte** com o PHP (golden). ✅
- `assinatura.py` — `assinar_dps` via `erpbrasil.assinatura`; mesmo `DigestValue` do gabarito. ✅
- `sefin.py` — transporte mTLS (`requests-pkcs12`, P12 direto), `POST /nfse`, `verificarDps`.
  **mTLS validado ao vivo** em homologação (handshake + `HEAD /dps`, read-only). ✅
- `danfse.py` — DANFSe local via `BrazilFiscalReport` ≥ 1.0 (validado com XML de NFS-e real). ✅
- `cli.py` — `nfse-nacional emitir` (`--pdf`/`--xml-out`/`--verbose`); logging com redação. ✅

**Emissão real VALIDADA em homologação** (24/06): com um certificado A1 real (Simples Nacional, RJ) o
SEFIN devolveu o `nNFSe` + a chave de 50 díg e o DANFSe foi gerado localmente. (No caminho, corrigido o
**E1229**: faltava o prolog `<?xml encoding="UTF-8"?>` no XML assinado.)

**DANFSe é dependência OPCIONAL** (`pip install PyNFSeNacionalGT[danfse]`): o núcleo de emissão usa só
deps permissivas; a `BrazilFiscalReport` (LGPL-3.0 pelo LICENSE/README upstream — o classifier AGPL do
pyproject deles parece engano) só entra para gerar o PDF. Import lazy em `danfse.py`.

**Falta (pré-publicação):** (1) criar o repo no GitHub + reservar o nome no PyPI; (2) endurecimento a
partir de emissões reais; (3) reportar o classifier de licença errado upstream.

Tooling: `pip install -e ".[dev]"` (deps instalam no 3.10–3.14), lock com hashes
(`requirements-dev.txt`), CI (`.github/workflows/ci.yml`), release por tag (`release.yml`).
Testes: `pytest` (67, +2 skip locais), `ruff check .`, `mypy --strict` — tudo verde.

## Regras

- **Nunca** commitar `.pfx`, `config/` real, `.env`, XML/PDF de nota real.
- Toda regra fiscal nova vai **primeiro** para `docs/conhecimento-fiscal.md`, depois para o código.
- Ao implementar DPS/assinatura: **diffar contra o gabarito PHP** antes de mandar pro SEFIN.
- Mensagem de commit termina com a linha de co-autoria do Claude Code quando aplicável.

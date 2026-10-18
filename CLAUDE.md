# CLAUDE.md — PyNFSeNacional

> Guia de desenvolvimento deste repositório. **Antes de qualquer tarefa, leia
> [`docs/conhecimento-fiscal.md`](docs/conhecimento-fiscal.md)** — é onde mora a regra fiscal
> (estrutura da DPS, E-codes, numeração, DANFSe). E o [`docs/roadmap.md`](docs/roadmap.md) para o
> escopo e a ordem de build.

## O que é

Pacote Python público (MIT) que emite **NFS-e pela API SEFIN Nacional** (DPS) e gera o **DANFSe
localmente**. Publicado no GitHub e no PyPI. Feito por um contador da **GT Contabilidade**
(https://gtcontabilidade.com) — que emite NFS-e nacional em produção e abriu o conhecimento — para
a comunidade que emite pelo padrão nacional.

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

**Lançado (1.x) — pipeline completo, em produção real.** Todas as peças estão implementadas; `Emissor.emitir()` roda
ponta a ponta: **validar → montar DPS → assinar → transporte mTLS → Nota** (+ `nota.danfse()`).

- `config.py` — dataclasses + `validar()` (E-codes) + loader tolerante. ✅
- `certificado.py` — leitura do `.pfx` via `cryptography` (+ fallback cifra legada §9). ✅
- `dps.py` — `montar_dps`/`id_dps`; o C14N do `infDPS` bate **byte-a-byte** com o PHP (golden). ✅
  - **Fix 25/06/2026:** a `<IM>` (Inscrição Municipal) saía DEPOIS do `<regTrib>` dentro de `<prest>`,
    violando a ordem do XSD (AnexoI) → **E1235** para todo prestador COM inscrição municipal. O golden
    (config sem IM) não pegava; pegou o **harness de paridade** do sistema consumidor, que diffa o
    infDPS contra a implementação de referência em PHP. Corrigido (IM antes do regTrib) + regressão
    `test_inscricao_municipal_vem_antes_do_regtrib`. ✅ Publicado na **v0.2.0** (junto com o bloco de
    endereço do tomador); a v0.1.0 do PyPI tem o bug da IM — pinar **≥0.2.0**.
  - **Feature 30/06/2026:** o `<toma>` passou a emitir os campos OPCIONAIS do tomador — `IM`,
    `<end>` (endereço nacional, bloco atômico), `<fone>`, `<email>` — na ordem do XSD (CPF|CNPJ →
    IM → xNome → end → fone → email; `end` = endNac(cMun,CEP) → xLgr → nro → xCpl? → xBairro).
    Aditivo: sem esses campos o XML é idêntico (golden segue bate-byte). Espelha o `buildTomador`
    do PHP de referência. Helper `_montar_end_toma` (atômico: omite o `end` inteiro se incompleto).
    Validado em homologação real (SEFIN aceitou `<toma>` com `<end>`+`<fone>`).
  - **Fix 24/07/2026 (MEI):** `opSimpNac=2` (MEI) tinha a mesma DPS do ME/EPP (`opSimpNac=3`) —
    errado. MEI é **isento** do valor aproximado dos tributos (**Decreto 8.264/2014**): `totTrib` usa
    `indTotTrib=0` (não `pTotTribSN`) e `regTrib` **omite** `regApTribSN`. Chaveamento no motor
    (`dps.py` `regTrib`/`totTrib`) + validador só exige `pTotTribSN` p/ `opSimpNac==3`. Regra em
    `docs/conhecimento-fiscal.md §3 "MEI"`; testes `test_mei_usa_indtottrib_e_omite_regaptribsn` e
    `test_mei_nao_exige_ptottribsn`. Descoberto no XML real do EmissorWeb de um MEI (Ibirité/MG).
  - **v0.5.0 (19/08/2026) — a IM é OPCIONAL de verdade.** Quem decide se a `<IM>` do prestador vai
    na DPS é o **CNC do município, POR CNPJ** (não por cidade): tem IM no CNC → mandar (senão
    **E0116**); não tem → **omitir** (mandar dá **E0120**). Dois prestadores da MESMA cidade podem
    exigir coisas opostas. Bug corrigido no caminho: IM com string em branco (`"   "`) emitia
    `<IM></IM>` **vazio** — agora só entra se sobrar dígito (`test_prestador_sem_im_omite_o_elemento`),
    e o `validar()` **recusa** IM sem dígito significativo (IM de enfeite vira nota real com dado
    falso). A omissão atômica do endereço do tomador passou a **logar WARNING** com os nomes dos
    campos que faltaram (nunca os valores). Regra completa em `docs/conhecimento-fiscal.md` §10–§13.
  - **Regime Regular + ISS retido (18/10/2026, não publicado):** `cNBS`, `tpRetPisCofins`,
    `pTotTrib`, grupo `IBSCBS` (classificação) e `tpRetISSQN=2` com `validar_retencao` (E0204/E0237),
    todos opcionais por config; `regApTribSN` virou exclusivo do ME/EPP (E0162). Alvo: a DPS que o
    PORTAL monta para um prestador do Lucro Presumido e o SEFIN autorizou — `tests/test_regime_regular.py`
    bate o C14N com ela e pina os hashes do Simples/MEI de antes. Regra em `docs/conhecimento-fiscal.md`
    §8, §12, §14 e §15.
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

**Publicado:** repo em github.com/Gomes343/PyNFSeNacional e pacote no PyPI (`PyNFSeNacionalGT`) —
release por tag `vX.Y.Z` (PyPI via Trusted Publishing + Release do GitHub, sem token no repo).
**Em aberto:** (1) endurecimento a partir de mais emissões reais; (2) grupo IBS/CBS do **Simples**
(01/01/2027) e os casos não cobertos do grupo; `pAliq`; (3) reportar o classifier de licença errado
upstream.

Tooling: `pip install -e ".[dev]"` (deps instalam no 3.10–3.14), lock com hashes
(`requirements-dev.txt`), CI (`.github/workflows/ci.yml`), release por tag (`release.yml`).
Testes: `pytest` (138 passed, +2 skip locais), `ruff check .`, `mypy --strict` — tudo verde.

## Regras

- **Nunca** commitar `.pfx`, `config/` real, `.env`, XML/PDF de nota real.
- Toda regra fiscal nova vai **primeiro** para `docs/conhecimento-fiscal.md`, depois para o código.
- Ao implementar DPS/assinatura: **diffar contra o gabarito PHP** antes de mandar pro SEFIN.
- Mensagem de commit termina com a linha de co-autoria do Claude Code quando aplicável.

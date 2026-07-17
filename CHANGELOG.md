# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [0.3.0] - 2026-07-17

### Alterado
- **Leiaute da DPS `1.00` → `1.01`** (RTC — NT SE/CGNFS-e nº 004 v2.0 / nº 007). Bump **defensivo**
  para as validações RTC que passam a ser obrigatórias em **03/08/2026**: há revisão oficial do
  XSD v1.01 cujo `TVerNFSe` casa **só `1.01`** (rejeita `1.00`), e `1.01` é aceito por todas as
  revisões. O atributo `versao` fica na **raiz `<DPS>`, fora do `infDPS` assinado** → o C14N/
  `DigestValue` e o *golden* **não mudam** (a paridade byte a byte com a referência PHP segue intacta).
  Validado em homologação **e em emissão de produção real** (notas emitidas em 1.01 e canceladas).

### Notas
- **IBS/CBS ainda não é emitido.** O grupo `IBSCBS` é **opcional no schema** (`minOccurs=0`). A
  obrigatoriedade de 03/08/2026 vale **só para Regime Regular** (Lucro Presumido/Real); o **Simples
  Nacional é dispensado** do destaque em 2026 (os campos do Simples só entram na NT 009, sem data de
  produção — destaque do Simples só em 2027). Segue no roadmap; ver `docs/conhecimento-fiscal.md` §8.

### Documentação
- Corrigida a nota de instalação do README (o pacote **já está publicado no PyPI**; pin recomendado
  `>=0.3.0`) e o status/roadmap de RTC (leiaute 1.01, IBS/CBS) em `README.md`, `docs/roadmap.md` e
  `docs/conhecimento-fiscal.md`.

## [0.2.0] - 2026-06-30

### Adicionado
- `dps.montar_dps`: o `<toma>` passou a emitir os campos **opcionais** do tomador — `IM`
  (Inscrição Municipal), `<end>` (endereço nacional, bloco atômico), `<fone>` e `<email>` — na ordem
  do XSD (AnexoI: `CPF|CNPJ → IM → xNome → end → fone → email`). **Aditivo:** sem esses campos o XML
  é idêntico ao anterior (o *golden* segue byte a byte). Validado em homologação real.

### Corrigido
- A `<IM>` do **prestador** era emitida **depois** do `<regTrib>`, violando a ordem do XSD (AnexoI)
  → **E1235** para todo prestador que tivesse Inscrição Municipal. Agora a `IM` vem **antes** do
  `regTrib`, com teste de regressão. ⚠️ A **v0.1.0** carrega esse bug — **pin `>=0.2.0`**.

## [0.1.0] - 2026-06-24

### Adicionado
- **Emissão ponta a ponta** de NFS-e pela API SEFIN Nacional (DPS):
  `config` → `certificado` → `montar_dps` → `assinar` → **transporte mTLS** → `Nota`.
- `dps.montar_dps`/`id_dps`: montagem da DPS (lxml, ordem do XSD AnexoI) com a lógica
  fiscal dos E-codes; o C14N do `infDPS` bate **byte a byte** com a referência PHP.
- `assinatura.assinar_dps`: XMLDSIG enveloped (RSA-SHA1) via `erpbrasil.assinatura` —
  mesmo `DigestValue` do gabarito de referência.
- `sefin.SefinClient`: transporte mTLS (`requests-pkcs12`, PKCS#12 direto), `POST /nfse`
  (gzip+base64), `verificarDps` (idempotência) e mapeamento de E-codes. **Emissão real validada
  em homologação** (certificado A1 real, Simples Nacional/RJ: nNFSe + chave de 50 díg + DANFSe).
- Correção **E1229**: o XML assinado precisa do prolog `<?xml encoding="UTF-8"?>` (o SEFIN rejeita
  sem ele) — `assinar_dps` reserializa com `xml_declaration=True`.
- `danfse.render`: DANFSe local (PDF) via `BrazilFiscalReport` ≥ 1.0 — **dependência opcional**
  (`pip install "PyNFSeNacionalGT[danfse]"`); o núcleo de emissão não a puxa (import lazy).
- `config.validar`/`validar_tomador`: portão de validação fiscal (E0312/E0712/E1235…,
  CPF/CNPJ mód-11) + loader tolerante (`ConfigError`).
- `Certificado`: leitura do `.pfx` A1 via `cryptography` (+ fallback de cifra legada §9).
- CLI `nfse-nacional emitir` (`--pdf`, `--xml-out`, `--verbose`); logging com redação
  (nunca loga senha do `.pfx` nem o XML com dados do tomador).
- Reprodutibilidade: lock com hashes (`requirements-dev.txt`), `mypy --strict`, CI em
  matriz 3.10–3.14, golden harness (`tests/golden/`).

### Limitações conhecidas / próximas versões
- Reportar upstream o classifier de licença errado da BrazilFiscalReport (LICENSE/README=LGPL-3.0,
  mas o classifier do pyproject diz AGPL-3.0).
- Tomador estrangeiro/sem documento; não-optantes (Lucro Presumido/Real); eventos
  (cancelamento); IBS/CBS (reforma tributária).

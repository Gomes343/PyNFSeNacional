# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [Não publicado]

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
  (`pip install "PyNFSeNacional[danfse]"`); o núcleo de emissão não a puxa (import lazy).
- `config.validar`/`validar_tomador`: portão de validação fiscal (E0312/E0712/E1235…,
  CPF/CNPJ mód-11) + loader tolerante (`ConfigError`).
- `Certificado`: leitura do `.pfx` A1 via `cryptography` (+ fallback de cifra legada §9).
- CLI `nfse-nacional emitir` (`--pdf`, `--xml-out`, `--verbose`); logging com redação
  (nunca loga senha do `.pfx` nem o XML com dados do tomador).
- Reprodutibilidade: lock com hashes (`requirements-dev.txt`), `mypy --strict`, CI em
  matriz 3.10–3.14, golden harness (`tests/golden/`).

### Pendente (pré-publicação)
- Criar o repositório no GitHub + reservar o nome no PyPI.
- Reportar upstream o classifier de licença errado da BrazilFiscalReport (LICENSE/README=LGPL-3.0,
  mas o classifier do pyproject diz AGPL-3.0).
- Tomador estrangeiro/sem documento; não-optantes (Lucro Presumido/Real); eventos
  (cancelamento); IBS/CBS (reforma tributária).

# Roadmap

> A estratégia é **integrar** as libs maduras do ecossistema fiscal Python e adicionar só o que
> falta (transporte ao SEFIN nacional + acabamento turnkey). Não reimplementar criptografia.

## Mapa: peça → biblioteca → o que falta

| # | Peça | Lib Python | Estado | O que escrevemos |
|---|---|---|---|---|
| 1 | Montar/serializar XML da DPS | `lxml` | ✅ usado direto | montar o `infDPS` na ordem do XSD (a lógica fiscal do §4) + C14N p/ a assinatura |
| 2 | Assinatura XMLDSIG | `erpbrasil.assinatura` | ✅ existe (em produção no Odoo Brasil) | configurar o perfil do DPS (Reference/Id `infDPS`) |
| 3 | Ler certificado A1 `.pfx` | `cryptography` | ✅ existe | wrapper + tratar cifra legada ICP-Brasil se aparecer |
| 4 | Transporte mTLS ao SEFIN | `requests` + **próprio** | ⚠️ não há p/ nacional | cliente HTTP: gzip+base64, POST, parse, idempotência (`verificarDps`) |
| 5 | DANFSe (PDF) | `BrazilFiscalReport` | ✅ existe (tem DANFSE) | confirmar layout nacional; aplicar os 2 fixes do §6 se necessário |
| 6 | CLI turnkey + orquestração | — | — | `Emissor`, contador de nDPS por ambiente, CLI |

## Escopo do v0.1 (mínimo que emite)

**Dentro:** um perfil só — o que já funciona em produção na referência:
- Prestador **Simples (ME/EPP)**, prestador = emitente (`tpEmit=1`).
- Tomador **com documento + nome** (CPF/CNPJ informado).
- Município que **já aderiu** ao ambiente nacional.
- Homologação **e** produção, com contadores separados.

**Fora do v0.1 (próximas versões):**
- IBS/CBS — o **leiaute** da DPS já está em **1.01** (RTC), mas o **grupo `IBSCBS` ainda não é
  emitido**: é obrigatório só para **Regime Regular** a partir de 03/08/2026 (Simples dispensado em
  2026). Ver §8 do conhecimento.
- Tomador estrangeiro / sem documento (consumidor final é só "omitir `<toma>`", esse entra fácil).
- Não-optantes (Lucro Presumido/Real) — usam `indTotTrib` em vez de `pTotTribSN`.
- Eventos (cancelamento, substituição).
- Auto-resolver razão social de CNPJ via BrasilAPI (conveniência).

## Fases de build (ordem por risco crescente)

1. **Scaffold + conhecimento** ✅
2. **Config + certificado** ✅ — `validar()` (E-codes) + loader tolerante; `.pfx` via `cryptography`
   (validado contra A1 ICP-Brasil real). + base de reprodutibilidade (lock com hashes, mypy, CI).
3. **Montar a DPS** ✅ — `montar_dps`/`id_dps` (lxml, ordem do XSD). O **C14N do `infDPS` bate
   byte-a-byte** com o gabarito da referência PHP (`tests/golden/`).
4. **Assinar** ✅ — `erpbrasil.assinatura` (signxml): mesmo `DigestValue` do gabarito (RSA-SHA1),
   `Reference=#Id`, assinatura **verifica**. Desrisco offline do ponto-chave, **sem o SEFIN**.
5. **Transporte mTLS** ✅ — `sefin.SefinClient` (`requests-pkcs12`, P12 direto, `verify=False`,
   gzip+base64, `POST /nfse`, `verificarDps`). **EMISSÃO REAL validada em homologação** (com um
   certificado A1 real, Simples Nacional/RJ): o SEFIN devolveu o `nNFSe` + chave de 50 díg; DANFSe
   gerado. No caminho, corrigido o **E1229** (faltava o prolog `<?xml encoding="UTF-8"?>` no XML assinado).
6. **DANFSe** ✅ — `danfse.render` via `BrazilFiscalReport[danfse]` ≥ 1.0; validado com um XML de
   NFS-e **real** (PDF gerado). Os 2 gotchas do §6 já vêm corrigidos upstream.
7. **CLI + empacotar** ✅ — `nfse-nacional emitir` (`--pdf`/`--xml-out`/`--verbose`); logging com
   redação; CHANGELOG; build (wheel/sdist) e workflow de release (PyPI Trusted Publishing por tag).

> **A estratégia do gabarito:** a referência PHP já assina/emite certo. Comparar a saída Python
> contra ela byte a byte transforma o ponto mais arriscado (a canonicalização XMLDSIG) num exercício
> de "igualar uma referência conhecida-boa" — sem ficar chutando contra o SEFIN.

## Decisões em aberto

- **Nome:** projeto/repo `PyNFSeNacional`; no **PyPI o pacote é `PyNFSeNacionalGT`** — `PyNFSeNacional`
  esbarra na proteção anti-typosquatting do PyPI (semelhante a `nfse-nacional`, de terceiro). Import
  `pynfsenacional`, CLI `nfse-nacional`. Trusted Publisher configurado (workflow `release.yml`, env `pypi`).
- **`requests` vs `httpx`** para o mTLS; e PKCS#12 direto (`requests-pkcs12`) vs converter p/ PEM.
- **Licença das deps:** `BrazilFiscalReport` é LGPL-3.0 (as demais, MIT). Usar como dependência
  (sem fork/edição) é compatível com um projeto MIT — documentar.
- **Contribuir upstream?** alternativa estratégica: levar o transporte SEFIN p/ o `nfelib` e o
  DANFSe nacional p/ o `BrazilFiscalReport`, em vez de (ou além de) pacote solo.

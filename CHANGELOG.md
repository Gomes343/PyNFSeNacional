# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [Não publicado]

## [1.1.0] - 2026-10-26

### Adicionado
- **Regime Regular (Não Optante — Lucro Presumido/Real)**, conferido contra a DPS que o próprio
  portal do governo monta e o SEFIN autoriza (§14): `servico.cNBS` (Item da NBS),
  `tributos.tpRetPisCofins` (domínio 0–9 da NT 007), `tributos.pTotTrib` (percentual aproximado
  federal/estadual/municipal, Lei 12.741) e o **grupo `IBSCBS`** (`servico.ibscbs`: `cIndOp`,
  `CST`, `cClassTrib`, `indFinal`, `finNFSe`/`indDest` = 0) — só a classificação; os valores o
  SEFIN calcula (§8).
- **ISS retido pelo tomador** (`tributos.tpRetISSQN=2`): `validar_retencao()` recusa antes do envio
  o tomador sem documento (**E0204**) ou sem endereço nacional completo (**E0237**); o `validar()`
  recusa a retenção de MEI (E0583), regime especial (E0588), serviço imune/exportado (E0580) e do
  ME/EPP que exigiria `pAliq` (E0621, ainda não emitido) — §15.
- `validar()` passa a acusar CST de PIS/COFINS tributável sem `tpRetPisCofins` (**E0698**).

### Corrigido
- **`regApTribSN` na DPS do Não Optante (E0162).** O campo saía para todo regime que não fosse MEI,
  e o default `1` da dataclass vazava para o `opSimpNac=1`. Agora é exclusivo do ME/EPP.

### Inalterado
- Sem os campos novos, a DPS do **Simples e do MEI sai byte-a-byte igual** (hashes do C14N pinados
  em `tests/test_regime_regular.py`, tirados do código anterior) e o golden segue bate-byte.

## [1.0.0] - 2026-10-14

> **Lançamento.** A biblioteca é o motor de produção de um escritório de contabilidade desde junho
> de 2026, com centenas de NFS-e autorizadas pelo SEFIN Nacional. Sai do *alpha*: a partir daqui a
> API pública (`Emissor`, `Nota`, `ClienteConfig` e o schema do config) segue **SemVer** — mudança
> incompatível só numa `2.0`.

### Corrigido
- **E0008 intermitente** ("data de emissão posterior ao processamento"). Além do fuso (a causa
  conhecida), havia uma segunda: `dhEmi` era o *piso* do segundo corrente, e a folga contra o
  relógio do SEFIN — cujo pool corre de ~0 a ~1s atrás — era sorteada a cada nota. Em produção,
  ~1 nota em 16 caía. Agora `dhEmi` nasce **recuado 5s** (`relogio.MARGEM_E0008_S`), com trava de
  meia-noite para nunca trocar a competência (`dCompet`). Um `dh_emi` explícito continua literal.

- **Instalação quebrada no Python 3.14.** A `erpbrasil.assinatura` 1.8.1 (30/09/2026) pôs teto
  `signxml<4` + `pyOpenSSL<24.3`, o que força `lxml<6` — sem wheel para o 3.14. A dependência
  passa a ser `erpbrasil.assinatura>=1.7,!=1.8.1`. Para a DPS o `signxml` 5 é seguro (a
  `Signature` é filha do `<DPS>`); o teste do golden confere posição, namespace e verificação.

### Adicionado
- **Informações complementares** (`servico.info_complementares` → `serv/infoCompl/xInfComp`):
  texto livre impresso no DANFSe, sem efeito fiscal. Vazio omite o grupo; truncado em 2000.

### Documentação
- **Calendário do IBS/CBS na NFS-e corrigido** (Ato Conjunto RFB/CGIBS nº 4/2026): obrigatório
  para o Regime Regular desde 01/10/2026 e para o **Simples Nacional a partir de 01/01/2027**; o
  SEFIN autoriza sem o grupo até 31/12/2026, mas a nota fica em desconformidade. A data de
  03/08/2026, citada antes, vale para NF-e/NFC-e. O grupo IBS/CBS é a **próxima prioridade**.
- Status "alpha" removido do README, do classifier (`5 - Production/Stable`) e da política de
  segurança (suporte à série `1.x`).

### Interno
- `nfelib` (e `xsdata`) saíram do lock de desenvolvimento — nunca foram importadas.

## [0.5.0] - 2026-08-19

> Release do **conhecimento de produção**: o que meses emitindo nota real ensinaram sobre
> Inscrição Municipal, CEP do tomador e CST de PIS/COFINS — mais as correções que esse
> conhecimento revelou no código.

### Corrigido
- **`<IM>` vazia no XML.** `prestador.inscricao_municipal` com string em branco (`""`, `"   "`)
  era "verdadeira" e emitia um elemento `<IM></IM>` **vazio** — falha de schema. Agora a IM só
  entra quando sobra **dígito** depois da limpeza (regressão
  `test_prestador_sem_im_omite_o_elemento`).

### Adicionado
- **A validação recusa Inscrição Municipal "de enfeite"** (`0000`, `ISENTO`, qualquer valor sem
  dígito significativo). Preencher a IM para "satisfazer o campo" ou é recusado pelo SEFIN, ou —
  pior — **passa**, e vira nota fiscal real com dado falso. Quando o CNC do município não tem IM
  para aquele CNPJ, o certo é deixar **vazio**.
- **A omissão do endereço do tomador deixou de ser silenciosa.** O bloco `<end>` é atômico
  (tudo-ou-nada): faltando `cMun`/`CEP`/logradouro/bairro, ele é descartado inteiro. Agora isso
  gera um **WARNING** dizendo **quais campos faltaram** — sem vazar valor nenhum. Guarda calada é
  bug com cara de sucesso: a nota saía "com sucesso" sem o endereço que o chamador achou que
  tinha enviado.
- **`servico.tributos.piscofins_cst` documentado** (default `"08"` = Operação sem Incidência;
  `"00"` = Nenhum). Já era configurável, mas não estava em lugar nenhum do schema publicado.

### Documentação
Quatro seções novas em `docs/conhecimento-fiscal.md`, todas nascidas de emissão real:
- **§10 — Inscrição Municipal: quem decide é o CNC, por CNPJ.** Não existe "o município X exige
  IM": o Cadastro Nacional de Contribuintes responde **por CNPJ**, e dois prestadores da mesma
  cidade podem exigir coisas opostas (**E0116** × **E0120** × nenhum erro — os três casos
  acontecem). Inclui o alerta de que **homologação mente** sobre IM/CNC — só produção responde a
  verdade — e que nem todo município existe em homologação.
- **§11 — E0240, o CEP que passa em toda validação e não existe.** Quase nunca é digitação: é o
  **CEP geral do município** (`xxxxx-000`) herdado de cadastro criado a partir da consulta de
  CNPJ. Como confirmar, como achar o certo e por que a validação de **formato** não pega.
- **§12 — CST de PIS/COFINS:** `08` (default, aceito em produção) × `00`, e por que o critério é o
  XML que o **próprio contribuinte** já emitiu — não se propaga de um prestador para outro.
- **§13 — Método: o XML que o contribuinte já emitiu é a fonte da verdade.** De notas antigas
  saem, provados, `cTribNac`+`cTribMun`, IM, séries em uso, CST e regime. Mais a disciplina da
  **nota canário** quando o município não existe em homologação.

E ainda:
- **§5 ganhou "quando o prestador já emitia por outro sistema"**: como o `Id` da DPS inclui a
  série, começar o contador em 1 numa série já usada **repete um `Id` existente** e o SEFIN
  devolve a nota **já emitida** — a idempotência funcionando contra você. Solução: **série
  dedicada**.
- Tabela de erros do §4 com **E0116, E0120, E0240, E0315 e E0676**.
- README: `cTribMun` deixou de ser descrito como obrigatório (é opcional desde a 0.4.0),
  exemplos de config anotados com IM/`piscofins_cst`/série, e uma seção **Origem** creditando a
  operação real que sustenta este projeto.

### Interno
- Sanitização de repositório público: nomes internos da implementação de referência saíram dos
  comentários, e os dados de teste passaram a ser **100% fictícios** (nenhuma entidade real).

## [0.4.0] - 2026-07-24

### Adicionado
- **MEI (`opSimpNac=2`): DPS distinta do ME/EPP (`opSimpNac=3`).** O MEI é **isento** do valor
  aproximado dos tributos (**Decreto 8.264/2014**) e recolhe os federais no DAS-SIMEI, então a DPS
  difere: `totTrib` usa **`indTotTrib=0`** (não `pTotTribSN`), `regTrib` **omite** `regApTribSN`, e
  **não** emite o bloco `tribFed` (PIS/COFINS) — senão **E0676**. Chaveamento por `opSimpNac` no
  `dps.py`; o validador só exige `pTotTribSN` quando `opSimpNac==3`. `opSimpNac=1` (Não Optante)
  também usa `indTotTrib`. Descoberto no XML real do EmissorWeb de um MEI (Ibirité/MG). Regressões
  `test_mei_usa_indtottrib_e_omite_regaptribsn` e `test_mei_nao_exige_ptottribsn`. Ver
  `docs/conhecimento-fiscal.md` §3 "MEI".
- **CNPJ alfanumérico (NT 2025.001):** a DPS **preserva as letras** do CNPJ (não força só dígitos) e
  o cálculo do DV usa o valor ASCII−48 de cada caractere. Cobre emitente e tomador. Vale a partir de
  jul/2026 (primeiros CNPJ alfanuméricos). Regressões em `test_cnpj_alfanumerico.py`.

### Alterado
- **`cTribMun` agora é OPCIONAL** (`minOccurs=0` no XSD): municípios sem desdobro (ex.: **Curitiba**)
  **rejeitam** o campo. Config sem `cTribMun` não gera mais E0312 — o `dps.py` **omite** o elemento.

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

# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [Não publicado]

## [1.7.0] - 2026-11-06

Revisão de robustez: o que é ambíguo ou demorado deixa de parecer falha (ou sucesso), e o
pacote passa a instalar uma pilha que assina em qualquer piso declarado.

### Corrigido
- **Cancelamento ambíguo lido como recusa.** Timeout depois do POST, conexão caída no meio, 5xx
  sem corpo e 2xx sem o evento viravam o mesmo "falhou" de uma recusa real (ou subiam como
  exceção) — e a nota que a SEFIN JÁ tinha cancelado seguia "válida" para quem chamou.
  `RespostaEvento.desfecho` (e `ResultadoEvento.desfecho`) diz agora `registrado`, `recusado`,
  `nao_enviado` ou `ambiguo` (+ a propriedade `ambiguo`); o `registrar_evento` não levanta mais por
  falha de rede. Sem retentativa automática.
- **E0840 no cancelamento direto** ("o evento de Cancelamento já está vinculado à NFS-e") é
  **conferido nos eventos da nota** antes de qualquer conclusão. ☠️ Medido em homologação: a SEFIN
  devolve o mesmo E0840 ao e101101 de uma nota que só tem o **pedido de análise** (e101103), que
  segue válida. Novos `SefinClient.evento_registrado(chave, tipo, seq=1)`,
  `SefinClient.situacao_cancelamento(chave)` (`cancelada` · `em_analise` · `indeferida` ·
  `sem_cancelamento`) e `sefin.conferir_e0840(cliente, chave)`. No `Emissor.cancelar`: com um
  evento que cancela (101101, 105102, 105104, 305101), `ok=True`, `cancelada=True`,
  `ja_estava_cancelada=True`, `desfecho="registrado"`; sem ele, `ok=False` e
  `desfecho="recusado"`; com a consulta falhando, `desfecho="ambiguo"`.
  `ResultadoEvento.situacao` diz o que a consulta achou. `RespostaEvento.ja_vinculado` expõe o
  E0840 a quem usa o `SefinClient` direto.
- **O cancelamento tem teto de relógio:** `Emissor.cancelar(..., prazo_s=90)`; estourado, é
  ambíguo. Sem ele, uma resposta que goteja prendia a chamada, porque o `timeout` vale entre bytes.
- **Justificativa até 255 caracteres**, o `TSMotivo` do XSD de eventos (a lib parava em 200).
- **CNPJ do autor começando com "NFS"** virava `CPFAutor`: o autor era limpo como a chave de acesso,
  que tira o prefixo `NFS`. Agora `eventos.limpar_autor`.
- **Chave de outro emitente:** `validar_cancelamento(..., autor=)` e `montar_cancelamento` recusam,
  antes de assinar, a chave cujo emitente não é o autor (`conferir_emitente=False` para procuração).
- **A senha do .pfx ia para a linha de comando do `openssl`** no fallback de cifra legada (legível em
  `/proc/<pid>/cmdline`), e a chave privada passava em claro por um arquivo temporário. Agora a
  senha vai pela entrada padrão e o PEM volta pela saída padrão.
- **O .pfx legado só abria no objeto `Certificado`:** a assinatura e o mTLS reliam o arquivo
  original e davam "senha inválida". `Certificado.pkcs12_bytes()` devolve o material que o objeto
  leu (o reembalado, no legado); `assinar_dps`/`assinar_xml` e `SefinClient` aceitam `pkcs12_data=`
  (alternativa a `cert_pfx_path`), e o `Emissor` usa os bytes.
- **CN sem ":"**: o CNPJ é procurado no CN (com DV válido) e, sem ele, na SAN ICP-Brasil
  (`2.16.76.1.3.3`; o CPF em `2.16.76.1.3.1`).
- **Caixa DF-e:** o XML embutido que não é UTF-8 era descartado calado e o NSU passava por cima.
  Agora `DocumentoDfe.xml_bytes` guarda os bytes, o texto sai pela codificação declarada, e
  `RespostaDfe.ilegiveis` lista os NSUs que não deu para ler (`DocumentoDfe.erro_xml`).
- **Consultas de parametrização:** um 404 sem a resposta do ADN, um corpo não-JSON (inclusive no
  200) e um 200 sem `parametrosConvenio`/`aliquotas` levantam `RuntimeError` (antes, "não existe").
  A entrada é conferida antes do GET (`ValueError`: município sem 7 dígitos, código fora de
  `00.00.00.000`, competência fora de `AAAA-MM-DD`). A `mensagem` do ADN fica em
  `SefinClient.ultima_mensagem_adn`.
- **Grupo Atividade/Evento:** o `validar()` acusa o **E0392** (o grupo fora do item 12, exceto o
  99.01.01), `id` com mais de 30 posições e data que não seja `AAAA-MM-DD` estrito (o
  `date.fromisoformat` do Python 3.11+ aceitava `20261104`, que o XSD recusa); o montador corta
  logradouro, número, complemento e bairro no tamanho do XSD e grava a data aparada.
- **Prestador de município com endpoint próprio** falava também com o **ADN** sem conferir o
  certificado do servidor. A conferência desligada vale só para o endpoint do município
  (`SefinClient.verificar_adn`).
- **`warnings.catch_warnings` em cada requisição** não era seguro entre threads (salva e restaura a
  lista GLOBAL de filtros): um "ignore" de uma thread ficava valendo para o processo. A requisição
  não mexe mais nos filtros; o aviso do .pfx BER é filtrado uma vez, no import, só por mensagem.
- **`import pynfsenacional` quebrava no Windows** sem o pacote `tzdata` (o `zoneinfo` de lá não tem
  a base do sistema). Agora `tzdata` é dependência no Windows e, sem a base, o relógio cai no UTC-3
  fixo (o mesmo fuso desde 2019).
- **`__version__` de uma instalação editável antiga** dizia a versão do metadado gravado (ex. 1.0.0)
  rodando o código novo: a versão é agora uma constante do código, lida pelo pyproject.

### Adicionado
- `dfe.sincronizar(..., prazo_s=…, ao_receber_pagina=…)` (e no `Emissor.sincronizar_dfe`): teto de
  relógio da sincronização inteira — estourado, devolve as páginas completas com `tem_mais=True` e
  `RespostaDfe.prazo_esgotado=True` — e gravação página a página (se o callback falhar, `parcial` e o
  `ultimo_nsu` no fim da página anterior).
- `DocumentoDfe.nome_arquivo()` (`<chave>.xml` / `<chave>_ev<NSU>.xml`: o `ChaveAcesso` do evento é
  a chave da nota, e o mesmo nome fazia o evento apagar a nota) e `DocumentoDfe.gravar(pasta)`
  (bytes, gravação atômica).
- `SefinClient(prazo_total_s=…)`, `timeout=(conectar, ler)` e `prazo_s=` por requisição
  (`registrar_evento`, `distribuicao_dfe`); `sefin.PrazoEsgotado`.
- `Certificado.documento` e `Certificado.tipo_documento` (`"CNPJ"` | `"CPF"`): o e-CPF do sócio não
  passa mais por e-CNPJ. O `cnpj` segue devolvendo o mesmo que antes (inclusive o CPF de um e-CPF).
- `chave.emitente_da_chave` / `chave.chave_do_emitente` (o CNPJ/CPF do emitente dentro da chave).
- `dfe.decodificar_xml`.

### Mudou
- ⚠️ **Comportamento que muda para quem já usa a 1.6.0** (cada um está descrito em "Corrigido"):
  - `SefinClient.registrar_evento` não levanta mais `requests.RequestException`: devolve
    `ok=False` com `desfecho` `nao_enviado` ou `ambiguo`. Quem tratava a exceção passa a ler o
    `desfecho`.
  - `eventos.montar_cancelamento` e `Emissor.cancelar` recusam por padrão (`ConfigError`, antes de
    assinar) a chave cujo emitente não é o autor. Pedido por procuração: `conferir_emitente=False`
    (nos dois).
  - `parametros_convenio`/`aliquotas` levantam `ValueError` para entrada fora do formato e
    `RuntimeError` para 404 sem a resposta do ADN ou corpo não-JSON (antes, `None`/`[]`).
- **Pisos de dependência** que de fato assinam: `signxml>=4` (declarado), `cryptography>=43`,
  `lxml>=5.2.1`, `erpbrasil.assinatura>=1.8.0`. Com os pisos antigos o resolvedor montava signxml
  3.2.2 + pyOpenSSL novo, e a suíte dava 11 falhas. O CI ganhou a célula **mínimas**
  (`.github/minimas.txt`) e o **Windows**.
- **Release:** a publicação no PyPI espera a suíte (o próprio CI), confere que a tag está no `main`
  e bate com `__version__` e com o CHANGELOG, e não usa mais `skip-existing`.
- **sdist** só com o pacote (`src/`, README, LICENSE, CHANGELOG); antes levava testes, docs e
  arquivos do repositório.
- Os testes do grupo Atividade/Evento usam dados fictícios.

### Documentação
- `docs/conhecimento-fiscal.md` §9 (fallback legado, titular), §16 (desfechos, E0840, 255,
  emitente), §17 (a 8ª posição da chave é o `ambGer`; emitente), §18 (nome do evento, bytes,
  prazo, ADN conferido), §20 (E0392, E0398, tamanhos, datas), §21 (404 do ADN, entrada conferida).

## [1.6.0] - 2026-11-05

### Adicionado
- **`pAliq` — a alíquota do ISS na DPS** (`servico.tributos.pAliq`), o que o ME/EPP com o ISS pelo
  Simples precisa quando o ISS é **retido** pelo tomador. Vai como último filho do `tribMun`; sem o
  campo, a DPS não muda um byte. O `validar()` acusa antes do envio: retido sem `pAliq` (E0621),
  abaixo de 1,8% (E0628), `pAliq` sem retenção (E0625) e acima do teto de 5% do ISS.
  Regra em `docs/conhecimento-fiscal.md` §15.

## [1.5.0] - 2026-11-05

### Adicionado
- **Parametrização do município no ADN** (só leitura): `Emissor.consultar_convenio()` diz se o
  município emite pelo ambiente nacional (`aderenteAmbienteNacional`) e
  `Emissor.consultar_aliquota(codigo, competencia)` traz as alíquotas que ele parametrizou para o
  serviço (`00.00.00.000`), ou o histórico sem competência. Também em `SefinClient`
  (`parametros_convenio`, `aliquotas`). O 404 do ADN vira `None` / lista vazia; outra falha levanta.
  Regra em `docs/conhecimento-fiscal.md` §21.

## [1.4.0] - 2026-11-05

### Adicionado
- **Grupo Atividade/Evento (`atvEvento`)**, obrigatório quando o `cTribNac` é do item 12 da lista
  (sem ele o SEFIN devolve **E0390**). Opcional por config em `servico.evento` (nome, início, fim e
  o local: `id` do evento **ou** endereço nacional). O `validar()` acusa o item 12 sem evento, datas
  inválidas, fim antes do início e endereço incompleto. Sem `evento`, a DPS não muda um byte.
  Regra em `docs/conhecimento-fiscal.md` §20.

## [1.3.2] - 2026-11-03

### Corrigido
- **`mesma_nota` lia o tomador diferente da DPS.** A DPS lê o documento em `cpf_cnpj`, `cpf` ou
  `cnpj`; a comparação lia `cpf_cnpj` ou `documento`. Com o tomador em `cnpj`/`cpf`, a nota já
  emitida (resposta perdida) parecia OUTRA: o contador pulava o número e a nota era enviada de
  novo. As duas leituras agora são uma só, `dps.documento_tomador`, e o documento do XML é
  normalizado como o da DPS. Com `documento`, que a DPS não leva, a nota sem `<toma>` deixa de
  parecer outra.

## [1.3.1] - 2026-11-01

### Corrigido
- **A recusa da distribuição DF-e lia como caixa vazia.** `sincronizar` tratava
  `StatusProcessamento: REJEICAO` como fim de leitura (`parcial=False`, `erro=None`), e o HTTP 400
  só como "HTTP 400" — o motivo se perdia. Medido em produção: consulta por procuração sem a
  procuração do serviço NFS-e volta 400 + `REJEICAO` + `E2245` ("Não há procuração da inscrição …").
  Agora a `RespostaDfe` diz `rejeitada=True`, `parcial=True`, guarda todos os `erros`
  (`{codigo, descricao, complemento}`) e `erro` traz "[E2245] …". Repetir não muda a resposta, então
  a recusa não se repete. Campos novos, nada removido.

## [1.3.0] - 2026-10-31

**A NT 009 implementada, pensada para 01/01/2027 — em fase de testes até a produção virar.** A
homologação do SEFIN aplica o leiaute novo desde 31/10/2026; a lib já emite nele, inclusive o grupo
IBS/CBS do Simples Nacional. A produção segue no leiaute atual (09/02/2026) e a DPS de produção não
mudou um byte. Quando a produção virar de pacote, a config força o novo com `"leiaute": "20261020"`.
Os campos do Simples que a NT 009 cria e o esquema publicado ainda não tem (`regApIBSCBSSN`,
`cAtvSN`) entram quando o pacote os trouxer.

### Adicionado
- **O leiaute da NT 009** (pacote de esquemas de 20/10/2026), que a homologação aplica desde
  31/10/2026 e recusava a DPS da lib com E1235. A lib monta os dois e escolhe pelo ambiente:
  homologação no `20261020`, produção no `20260209` (a DPS de produção não mudou um byte). A
  config pode forçar com `"leiaute"`, para a virada da produção. No novo: `finNFSe` no `infDPS`
  (em toda DPS), `xDescServ` depois do `cNBS`, e `CST`/`cClassTrib` direto em `IBSCBS/valores/trib`.
  Validado ao vivo em homologação (§19).
- O E1235 que cita o `finNFSe` ganha, no fim da mensagem, qual leiaute configurar — é o sinal de
  que a produção virou de pacote antes da lib. O `[E1235]` segue no começo.
- `validar()` recusa o grupo IBS/CBS sem o Item da NBS (**E0322**), medido em homologação.
- Os esquemas oficiais dos dois pacotes em `tests/xsd/`: toda DPS que a suíte monta (8 configs × 3
  tomadores × 2 leiautes) é validada contra o XSD do seu leiaute.

### Documentação
- §19 (os dois leiautes) e, na §8, o grupo IBS/CBS do **Simples** autorizado em homologação, o
  E0322 e o Anexo VIII (de onde tirar NBS, `cIndOp` e `cClassTrib` por item).

## [1.2.1] - 2026-11-01

Publicada no PyPI a partir de um commit **fora do `main`** (`6ea182e`, hoje no ramo
`release/1.2.x`), sem passar pelo CI, depois da 1.3.0. O conteúdo é o mesmo conserto que a 1.3.1
trouxe para o `main`, aplicado sobre a 1.2.0. Fica registrada para quem fixa `~=1.2.0`.

### Corrigido
- **A recusa da distribuição DF-e lia como caixa vazia** (`REJEICAO` / HTTP 400, ex. E2245 sem
  procuração) — ver a 1.3.1.

## [1.2.0] - 2026-10-31

### Corrigido
- **O contador de nDPS travava depois de uma resposta perdida.** Se o envio saía e a resposta não
  voltava (timeout), o contador não avançava; na emissão seguinte o `verificarDps` achava a DPS
  antiga e devolvia `ja_emitida` — também sem avançar. Dali em diante TODA nota nova voltava "já
  emitida" com a chave da antiga, e nenhuma saía. Agora o contador avança, e a lib confere se a
  DPS achada é a mesma nota (valor + documento do tomador): é → `ja_emitida`; é outra (contador
  atrasado) → pula o número e emite; sem como conferir → `ja_emitida` (o ambíguo conta como feito).
  Quem passa `numero=` explícito não é afetado.
- O contador nunca recua (`_commit_numero` grava o maior entre o atual e o usado + 1).

### Adicionado
- **Cancelamento**: `Emissor.cancelar(chave, justificativa=…, motivo=1, modo="direto"|"analise")` —
  e101101 (direto) e e101103 (análise fiscal, para o município que recusa o direto com E0823).
  Valida motivo (1/2/9) e justificativa (15–200) antes de assinar. O pedido sai idêntico, byte a
  byte, ao da implementação de referência em produção; validado em homologação (§16).
- **Consulta pela chave**: `Emissor.consultar(chave)` → `Nota` com o XML (DANFSe), ou `None`.
- **Distribuição DF-e**: `Emissor.sincronizar_dfe(nsu)` → `RespostaDfe` com as NFS-e emitidas,
  recebidas e os eventos do CNPJ, por NSU, com pausa entre páginas e nova tentativa no HTTP 429
  (§18). `DocumentoDfe.classificar(cnpj)` diz "emitida", "recebida" ou "evento".
- CLI: `nfse-nacional consultar`, `cancelar` e `dfe`.
- A nota recuperada (`ja_emitida`) volta com o **XML** (antes, só a chave — sem DANFSe) e com o
  `nNFSe`, tirado da chave quando o XML não vem (`pynfsenacional.chave`).
- `Nota.erros` e `RespostaSefin.erros`: **todos** os erros da resposta (antes só o primeiro chegava).
  O `erro_msg` continua começando por `[E0xxx]` e traz os demais depois de ` | `.
- Falha HTTP sem E-code vem explicada: `"resposta não-JSON (HTTP 503) — SEFIN fora do ar (serviço
  indisponível)"`; 401/403 apontam o certificado, 429 pede para esperar. O `HTTP NNN` segue no texto.
  `RespostaSefin.http_status` guarda o status.
- `py.typed`: a tipagem (`mypy --strict`) chega a quem instala o pacote.

### Mudado
- **O certificado do servidor da SEFIN é conferido** (`verify` ligado). A cadeia é pública
  (GlobalSign/SERPRO; o ADN usa Let's Encrypt), medido nos dois ambientes. Os endpoints próprios
  de município (Catanduva) seguem sem conferência por padrão. `SefinClient(verificar_servidor=…)`
  aceita `True`, `False` ou o caminho de um CA bundle.
- **Valor em `Decimal`.** `emitir(valor=…)` aceita `Decimal`, `int`, `str` (`"1.262,90"` ou
  `"1262.90"`) e `float` (convertido via `str`, sem o erro binário), com arredondamento comercial.
  Valor zero, negativo ou ilegível é recusado com `ConfigError` antes de tocar a rede.

### Aviso
- Em 31/10/2026 a **homologação** passou a recusar a DPS do leiaute atual (E1235: espera
  `cMotivoEmisTI`/`finNFSe` antes do `cLocEmi`). A produção segue aceitando. Ver §1.

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

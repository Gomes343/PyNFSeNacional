# Política de Segurança

Este é um pacote **fiscal** que lida com certificados digitais e assinatura de documentos. Levamos
segurança a sério.

## Versões suportadas

O projeto está em **alpha** (`0.1.x`). Correções de segurança vão para a última versão da série
`0.1.x`. Não há suporte retroativo a versões anteriores durante o alpha.

## Reportar uma vulnerabilidade

**Não abra uma issue pública** para vulnerabilidades. Use o canal privado do GitHub:

> **Security → Report a vulnerability** (GitHub Security Advisories) no repositório.

Descreva o impacto, os passos para reproduzir e a versão. Responderemos o mais rápido possível e
combinaremos a divulgação coordenada após a correção.

### ⚠️ Ao reportar, NUNCA inclua dados reais

- **Nada** de certificados A1 (`.pfx`/`.p12`), senhas, `.env` ou tokens.
- **Nada** de CNPJ/CPF, nomes ou XML/PDF de **notas reais**.

Reproduza com **dados fictícios** (ex.: CNPJ de teste `11222333000181`, CPF `11144477735`) e
**certificados de teste descartáveis** (self-signed) — exatamente como as fixtures deste repositório.

## Boas práticas para quem usa o pacote

- O `.pfx` e as configs reais **nunca** devem ir para o controle de versão (o `.gitignore` deste
  projeto já bloqueia esses padrões — replique no seu).
- Guarde a **senha do certificado** fora do código (variável de ambiente / cofre de segredos).
- A biblioteca **não loga** a senha do `.pfx` nem o XML com dados do tomador; mantenha esse cuidado
  ao integrar (configure o `logging` da sua aplicação com isso em mente).
- Trate o XML da NFS-e e o DANFSe como **dados fiscais sensíveis** (contêm CPF/CNPJ do tomador).

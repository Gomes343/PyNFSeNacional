# Como contribuir

Obrigado pelo interesse! Este é um projeto da comunidade fiscal Python brasileira. Toda ajuda é
bem-vinda — relatos de erro, melhorias de documentação, suporte a mais municípios/regimes, testes.

## Antes de tudo: regra de ouro 🔒

**NUNCA** inclua material sensível em commits, issues ou PRs:

- certificados A1 (`.pfx`/`.p12`/`.pem`/`.key`), senhas, `.env`, tokens;
- CNPJ/CPF, nomes ou XML/PDF de **notas reais**.

O [`.gitignore`](.gitignore) já bloqueia esses padrões; os dados de exemplo e fixtures são **fictícios**.
Se precisar reproduzir um problema, **anonimize** (use CNPJ/CPF de teste, ex.: `11222333000181`).

## Ambiente de desenvolvimento

```bash
git clone https://github.com/Gomes343/PyNFSeNacional.git
cd PyNFSeNacional
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # dev já inclui o extra [danfse]
```

## Antes de abrir o PR

Tudo precisa passar (é o que a CI roda, na matriz 3.10–3.14):

```bash
ruff check .          # lint + ordenação de imports
mypy                  # tipos (strict)
pytest                # testes (inclui o golden contra a referência)
```

- **Regra fiscal nova** vai **primeiro** para [`docs/conhecimento-fiscal.md`](docs/conhecimento-fiscal.md),
  depois para o código (o porquê fiscal precisa estar documentado).
- Mexeu na **montagem da DPS ou na assinatura**? O *golden* (`tests/golden/`) compara a saída ao
  gabarito de referência byte a byte. Se a mudança for legítima, regenere com
  `bash tests/golden/regenerar_gabarito.sh` e explique o porquê no PR.
- Mantenha o **núcleo de emissão sem dependências pesadas**; PDF/extras ficam atrás de `[danfse]`.

## Estilo de commit

Mensagens em **português**, no imperativo, dizendo **o quê** e **por quê** (não só o "como").
Um assunto curto + corpo quando precisar de contexto.

## Pull Requests

1. Crie um branch a partir de `main`.
2. Mantenha o PR focado num assunto.
3. Descreva o **porquê**, como testou, e marque itens do checklist do template.
4. CI verde é pré-requisito de merge.

Dúvidas? Abra uma [issue](https://github.com/Gomes343/PyNFSeNacional/issues) — de preferência antes de
um PR grande, para alinharmos a abordagem.

# data-exports

Pasta de exportacoes e analises de dados dos projetos do VPS.

## Blog metrics

- Script: `export-blog-metrics.sh`
- Serie real: `exports/blog/daily_snapshot.csv`
  - Colunas: `snapshot_date, total_posts, total_views, total_comentarios, aprovados, rejeitados, taxa_aprovacao_pct, posts_ultimos_7d`
  - Cobertura verificada: 121 dias, 2026-07-21 .. 2026-11-18
  - Estatisticas observadas: views/dia media ~398 (max 1000); `total_comentarios`, `aprovados`, `rejeitados` permanecem 0 na serie toda.

## Analise de engajamento por tipo (estudo de caso)

Objetivo do pedido original: **analisar engajamento e testar hipoteses por tipo de jogo.**

### Por que o estudo de caso usa o CSV do blog

- O sistema `jogandologica` (backend em `/opt/jogandologica-api`, DB `data/jogandologica.db`)
  tem uma unica linha em `activity_events`. O schema tem `activity_type`, `module_id`,
  `score`, `duration_seconds`, `correct_answers`, `total_questions`, `occurred_at`,
  mas com **N=1** nao e possivel inferencia estatistica honesta.
- Optamos por nao inventar dataset. Reinterpretamos "tipo de jogo" como
  **tipo de interacao** entre dois regimes observaveis no dataset real do blog:
  `renovacao_alta` (posts_ultimos_7d >= mediana=5) e `renovacao_baixa`
  (posts_ultimos_7d < mediana). Eixo equivalente ao "tipo de conteudo" que
  sustenta o engajamento diario.
- A limitacao fica declarada e nao mascarada.

### Metodologia

- `analysis/engagement_analysis.py` (Python 3.12, stdlib pura).
- Segmentacao por mediana de `posts_ultimos_7d`.
- Hipotese:
  - **H0**: engajamento medio (`total_views`) igual entre renovacao ALTA e BAIXA.
  - **H1**: engajamento medio maior no grupo de renovacao ALTA.
- Estatisticas:
  - **Welch t-test** (variancias desiguais) + p bilateral.
  - **Mann-Whitney U** (nao parametrico) + p bilateral via aproximacao normal.
  - **IC95% da diferenca de medias** (Welch).
  - **Bootstrap 5000 iteracoes** (seed=20261119) para IC95% das medias por grupo e global.
  - **Pearson r** e p bilateral para `total_posts` vs `total_views` e
    `posts_ultimos_7d` vs `total_views`.

### Saidas

- `exports/blog/engagement_by_group.csv` — resumo estatistico por grupo + IC95%.
- `exports/blog/engagement_findings.json` — hipoteses, p-valores, ICs, correlacoes.

### Como rodar

```bash
cd /edu/data-exports
python3 analysis/engagement_analysis.py
```

Retorna `0` em sucesso. Sem dependencias externas.

### Limitacoes declaradas

- `total_comentarios`, `aprovados`, `rejeitados` sao sempre 0 no CSV; nao inferimos
  sobre engajamento qualitativo nem taxa de aprovacao real.
- A atribuicao causal `renovacao -> engajamento` **nao** e provada; apenas testada
  associacao com IC e p-valor. O desenho e observacional.
- Nao ha teste de jogos do `jogandologica`; o schema esta documentado acima para
  uma proxima rodada, quando houver massa de dados.

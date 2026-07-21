#!/bin/bash
# Exporta metricas do blog para CSV e envia ao GitHub (camada bronze do medalhao)
set -e
DATA=$(TZ=America/Sao_Paulo date +%F)
BASE=/edu/data-exports
DIR=$BASE/exports/blog/$DATA
mkdir -p "$DIR"

PSQL="docker exec ap_postgres psql -U ap_user -d ap_saas --csv -c"

# posts.csv - snapshot completo por post
$PSQL "SELECT p.id, p.slug, p.title, p.tema, p.\"fonteIA\", p.status, array_to_string(p.keywords, ';') AS keywords, p.views, LENGTH(p.content) AS tamanho_conteudo, (p.\"imageSvg\" IS NOT NULL) AS tem_imagem, p.\"createdAt\", p.\"updatedAt\", COUNT(c.id) AS comentarios_total, COUNT(c.id) FILTER (WHERE c.status = 'aprovado') AS comentarios_aprovados, COUNT(c.id) FILTER (WHERE c.status = 'rejeitado') AS comentarios_rejeitados FROM \"BlogPost\" p LEFT JOIN \"BlogComment\" c ON c.\"postId\" = p.id GROUP BY p.id ORDER BY p.\"createdAt\"" > "$DIR/posts.csv"

# comments.csv - por comentario (sem texto completo, so tamanho)
$PSQL "SELECT c.id, p.slug AS post_slug, c.nome, c.status, LENGTH(c.texto) AS tamanho_texto, c.\"moderacaoIA\", c.\"createdAt\" FROM \"BlogComment\" c JOIN \"BlogPost\" p ON p.id = c.\"postId\" ORDER BY c.\"createdAt\"" > "$DIR/comments.csv"

# daily_snapshot.csv - serie temporal append-only
SNAP=$BASE/exports/blog/daily_snapshot.csv
if [ ! -f "$SNAP" ]; then
  echo "snapshot_date,total_posts,total_views,total_comentarios,aprovados,rejeitados,taxa_aprovacao_pct,posts_ultimos_7d" > "$SNAP"
fi
docker exec ap_postgres psql -U ap_user -d ap_saas -t --csv -c "SELECT '$DATA', COUNT(DISTINCT p.id), COALESCE(SUM(DISTINCT_VIEWS.v),0), COUNT(c.id), COUNT(c.id) FILTER (WHERE c.status='aprovado'), COUNT(c.id) FILTER (WHERE c.status='rejeitado'), COALESCE(ROUND(100.0 * COUNT(c.id) FILTER (WHERE c.status='aprovado') / NULLIF(COUNT(c.id),0), 1), 0), COUNT(DISTINCT p.id) FILTER (WHERE p.\"createdAt\" >= NOW() - INTERVAL '7 days') FROM \"BlogPost\" p LEFT JOIN LATERAL (SELECT p.views AS v) DISTINCT_VIEWS ON true LEFT JOIN \"BlogComment\" c ON c.\"postId\" = p.id" >> "$SNAP"

# commit + push
cd $BASE
git add -A
if git diff --cached --quiet; then
  echo "[$(date)] Nada novo para commitar."
else
  git commit -m "export blog metrics $DATA"
  git push -u origin main
  echo "[$(date)] Export $DATA enviado ao GitHub."
fi

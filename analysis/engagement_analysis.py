#!/usr/bin/env python3
"""
Analise de engajamento por tipo (estudo de caso real).

Origem dos dados: exports/blog/daily_snapshot.csv (121 dias, 2026-07-21..2026-11-18)
Projeto: /edu/data-exports

Escopo adaptado (ver README.md):
- O sistema "jogandologica" tem apenas N=1 atividade real no banco
  (/opt/jogandologica-api/data/jogandologica.db), insuficiente para inferencia.
- Usamos o dataset real e continuo do blog (121 dias) como eixo de "tipo de
  interacao": dias com renovacao de conteudo na janela 7d (posts_ultimos_7d>0)
  vs dias sem renovacao na janela (posts_ultimos_7d==0).
- Confounder temporal reconhecido: o periodo "cedo" tem p7d=0 e poucas views;
  o periodo "tarde" tem p7d>0 e mais views. Alem do teste global, fazemos
  analise estratificada por periodo (mediana da snapshot_date) para desempatar.

Implementacao: stdlib pura (Python 3.12). Sem pandas/scipy.
"""
from __future__ import annotations
import csv
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CSV_IN = ROOT / "exports" / "blog" / "daily_snapshot.csv"
CSV_OUT_GROUPS = ROOT / "exports" / "blog" / "engagement_by_group.csv"
JSON_OUT = ROOT / "exports" / "blog" / "engagement_findings.json"

SEED = 20261119
N_BOOT = 5000


def load_rows():
    rows = []
    with CSV_IN.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "date": r["snapshot_date"],
                "total_posts": int(r["total_posts"]),
                "total_views": int(r["total_views"]),
                "total_comentarios": int(r["total_comentarios"]),
                "aprovados": int(r["aprovados"]),
                "rejeitados": int(r["rejeitados"]),
                "taxa_aprovacao_pct": float(r["taxa_aprovacao_pct"]),
                "posts_ultimos_7d": int(r["posts_ultimos_7d"]),
            })
    return rows


def mean(xs): return sum(xs) / len(xs) if xs else float("nan")


def stdev(xs):
    n = len(xs)
    if n < 2: return float("nan")
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def median(xs):
    s = sorted(xs); n = len(s)
    if n == 0: return float("nan")
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def betacf(a, b, x, maxit=200, eps=3e-12):
    qab = a + b; qap = a + 1.0; qam = a - 1.0
    c = 1.0; d = 1.0 - qab * x / qap
    if abs(d) < 1e-30: d = 1e-30
    d = 1.0 / d; h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30: d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30: c = 1e-30
        d = 1.0 / d; h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30: d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30: c = 1e-30
        d = 1.0 / d; de = d * c; h *= de
        if abs(de - 1.0) < eps: break
    return h


def betainc(a, b, x):
    if x <= 0.0: return 0.0
    if x >= 1.0: return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * betacf(a, b, x) / a
    return 1.0 - bt * betacf(b, a, 1.0 - x) / b


def t_cdf(t, df):
    x = df / (df + t * t)
    ib = betainc(df / 2.0, 0.5, x)
    if t >= 0:
        return 1.0 - 0.5 * ib
    return 0.5 * ib


def t_welch(x, y):
    nx, ny = len(x), len(y)
    if nx < 2 or ny < 2:
        return (float("nan"), float("nan"), 1.0)
    mx, my = mean(x), mean(y)
    sx, sy = stdev(x), stdev(y)
    se2 = sx * sx / nx + sy * sy / ny
    if se2 <= 0: return (float("nan"), float("nan"), 1.0)
    t = (mx - my) / math.sqrt(se2)
    df = (se2 ** 2) / ((sx * sx / nx) ** 2 / (nx - 1) + (sy * sy / ny) ** 2 / (ny - 1))
    p = 2.0 * (1.0 - t_cdf(abs(t), df))
    return (t, df, p)


def mann_whitney_u(x, y):
    nx, ny = len(x), len(y)
    if nx == 0 or ny == 0:
        return (float("nan"), 1.0)
    comb = [(v, 0) for v in x] + [(v, 1) for v in y]
    comb.sort()
    rank = [0.0] * len(comb)
    i = 0
    while i < len(comb):
        j = i
        while j + 1 < len(comb) and comb[j + 1][0] == comb[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            rank[k] = avg
        i = j + 1
    r1 = sum(rank[k] for k in range(len(comb)) if comb[k][1] == 0)
    u = r1 - nx * (nx + 1) / 2.0
    mu = nx * ny / 2.0
    sd = math.sqrt(nx * ny * (nx + ny + 1) / 12.0)
    if sd == 0: return (u, 1.0)
    z = (u - mu) / sd
    p = math.erfc(abs(z) / math.sqrt(2.0))
    return (u, p)


def bootstrap_ci(x, n=N_BOOT, alpha=0.05, seed=SEED):
    n_x = len(x)
    if n_x < 2:
        return (float("nan"), float("nan"))
    rnd = random.Random(seed)
    means = []
    for _ in range(n):
        means.append(sum(rnd.choice(x) for _ in range(n_x)) / n_x)
    means.sort()
    lo = means[int((alpha / 2) * n)]
    hi = means[int((1 - alpha / 2) * n) - 1]
    return lo, hi


def welch_ci(x, y, alpha=0.05):
    nx, ny = len(x), len(y)
    if nx < 2 or ny < 2:
        return (float("nan"), float("nan"))
    mx, my = mean(x), mean(y)
    sx, sy = stdev(x), stdev(y)
    se2 = sx * sx / nx + sy * sy / ny
    df = (se2 ** 2) / ((sx * sx / nx) ** 2 / (nx - 1) + (sy * sy / ny) ** 2 / (ny - 1))
    se = math.sqrt(se2)
    lo, hi = 0.0, 10.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if t_cdf(mid, df) < 0.975:
            lo = mid
        else:
            hi = mid
    tcrit = (lo + hi) / 2.0
    return (mx - my) - tcrit * se, (mx - my) + tcrit * se


def pearson_r(x, y):
    n = len(x)
    if n < 3: return (float("nan"), 1.0)
    mx, my = mean(x), mean(y)
    sx, sy = stdev(x), stdev(y)
    if sx == 0 or sy == 0: return (float("nan"), 1.0)
    r = sum((a - mx) * (b - my) for a, b in zip(x, y)) / ((n - 1) * sx * sy)
    if abs(r) >= 1.0: return (r, 0.0)
    t = r * math.sqrt((n - 2) / (1 - r * r))
    p = 2.0 * (1.0 - t_cdf(abs(t), n - 2))
    return (r, p)


def describe(xs):
    return {
        "n": len(xs),
        "mean": mean(xs),
        "stdev": stdev(xs),
        "median": median(xs),
        "min": min(xs) if xs else None,
        "max": max(xs) if xs else None,
    }


def test_group(label_a, va, label_b, vb):
    t_stat, df, p_t = t_welch(va, vb)
    u_stat, p_u = mann_whitney_u(va, vb)
    lo, hi = welch_ci(va, vb)
    return {
        "grupo_a": label_a, "grupo_b": label_b,
        "n_a": len(va), "n_b": len(vb),
        "mean_a": mean(va), "mean_b": mean(vb),
        "welch_t": t_stat, "welch_df": df, "welch_p_2sided": p_t,
        "mann_whitney_U": u_stat, "mann_whitney_p_2sided": p_u,
        "welch_ci95_diff_a_menos_b": [lo, hi],
    }


def main() -> int:
    if not CSV_IN.exists():
        print(f"ERRO: {CSV_IN} nao existe", file=sys.stderr)
        return 2
    rows = load_rows()
    n = len(rows)
    if n < 10:
        print(f"ERRO: apenas {n} linhas; insuficiente para inferencia", file=sys.stderr)
        return 3

    # ---- eixo de tipo (renovacao na janela 7d) ----
    # ALTA: posts_ultimos_7d > 0; BAIXA: == 0
    grupo_a = [r for r in rows if r["posts_ultimos_7d"] > 0]
    grupo_b = [r for r in rows if r["posts_ultimos_7d"] == 0]
    va = [r["total_views"] for r in grupo_a]
    vb = [r["total_views"] for r in grupo_b]

    # ---- eixo temporal (mediana da data) para checar confounder ----
    med_date = median(list(range(n)))  # indice da mediana (dados estao ordenados)
    early = rows[:int(med_date) + 1]
    late = rows[int(med_date) + 1:]
    ve = [r["total_views"] for r in early]
    vl = [r["total_views"] for r in late]
    # dentro de cada periodo, renovacao>0 vs ==0 (quando existir)
    early_a = [r["total_views"] for r in early if r["posts_ultimos_7d"] > 0]
    early_b = [r["total_views"] for r in early if r["posts_ultimos_7d"] == 0]
    late_a = [r["total_views"] for r in late if r["posts_ultimos_7d"] > 0]
    late_b = [r["total_views"] for r in late if r["posts_ultimos_7d"] == 0]

    ci_a = bootstrap_ci(va)
    ci_b = bootstrap_ci(vb)
    ci_all = bootstrap_ci([r["total_views"] for r in rows])

    xs = [r["total_posts"] for r in rows]
    ys = [r["total_views"] for r in rows]
    r_pear, p_pear = pearson_r(xs, ys)
    xs2 = [r["posts_ultimos_7d"] for r in rows]
    r_pear2, p_pear2 = pearson_r(xs2, ys)
    r_pear3, p_pear3 = pearson_r(list(range(n)), ys)  # tempo (indice) x views

    findings = {
        "fonte": str(CSV_IN.relative_to(ROOT)),
        "n_dias": n,
        "periodo": f'{rows[0]["date"]}..{rows[-1]["date"]}',
        "eixo_tipo_escolhido": "renovacao_7d (>0 vs ==0) — proxy de tipo de interacao",
        "grupo_renovacao_positiva": {**describe(va), "ci95_bootstrap": ci_a},
        "grupo_renovacao_zero": {**describe(vb), "ci95_bootstrap": ci_b},
        "todos": {**describe(ys), "ci95_bootstrap_total_views": ci_all},
        "hipotese_principal": {
            "H0": "views/dia medio igual entre renovacao>0 e renovacao==0",
            "H1": "views/dia medio maior no grupo renovacao>0",
            "teste_global": test_group("renovacao_pos", va, "renovacao_zero", vb),
            "teste_estratificado_early": test_group("renovacao_pos_early", early_a, "renovacao_zero_early", early_b),
            "teste_estratificado_late": test_group("renovacao_pos_late", late_a, "renovacao_zero_late", late_b),
            "teste_tempo_early_vs_late": test_group("early", ve, "late", vl),
            "n_early": len(early), "n_late": len(late),
            "n_early_pos": len(early_a), "n_early_zero": len(early_b),
            "n_late_pos": len(late_a), "n_late_zero": len(late_b),
        },
        "correlacao": {
            "pearson_total_posts_vs_total_views": {"r": r_pear, "p": p_pear},
            "pearson_posts_ultimos_7d_vs_total_views": {"r": r_pear2, "p": p_pear2},
            "pearson_indice_tempo_vs_total_views": {"r": r_pear3, "p": p_pear3},
        },
        "limitacoes": [
            "total_comentarios/aprovados/rejeitados = 0 em todo o CSV; nao inferimos sobre esses campos.",
            "Confounder temporal: dias antigos tem p7d=0 e menos views. Teste estratificado cobre isso.",
            "Estudo observacional; nao ha atribuicao causal 'renovacao -> views'.",
            "jogandologica.db ainda tem apenas 1 activity_event; nao ha teste sobre 'tipo de jogo' ainda.",
        ],
    }

    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(findings, indent=2, ensure_ascii=False), encoding="utf-8")

    with CSV_OUT_GROUPS.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["grupo", "n", "views_media", "views_desvio", "views_mediana",
                    "views_min", "views_max", "ci95_lo", "ci95_hi"])
        for nome, dados, ci in (("renovacao_pos", describe(va), ci_a),
                                 ("renovacao_zero", describe(vb), ci_b)):
            w.writerow([nome, dados["n"], round(dados["mean"], 2),
                        round(dados["stdev"], 2), round(dados["median"], 2),
                        dados["min"], dados["max"],
                        round(ci[0], 2), round(ci[1], 2)])

    def f(x):
        if isinstance(x, float):
            return "nan" if math.isnan(x) else f"{x:.4f}"
        return str(x)

    print("== Estudo de engajamento por tipo (dados reais) ==")
    print(f"Fonte: {findings['fonte']}  |  n_dias: {n}  |  periodo: {findings['periodo']}")
    print(f"Eixo de tipo: {findings['eixo_tipo_escolhido']}")
    print()
    print("Grupo renovacao>0 :", describe(va), "IC95%", tuple(round(c, 2) for c in ci_a))
    print("Grupo renovacao=0 :", describe(vb), "IC95%", tuple(round(c, 2) for c in ci_b))
    print("Engajamento global:", describe(ys), "IC95%", tuple(round(c, 2) for c in ci_all))
    print()
    print("Hipotese H1 (renovacao>0 tem mais views que renovacao=0):")
    tg = findings["hipotese_principal"]["teste_global"]
    print(f"  Welch t={f(tg['welch_t'])} df={f(tg['welch_df'])} p={f(tg['welch_p_2sided'])}")
    print(f"  Mann-Whitney U={f(tg['mann_whitney_U'])} p={f(tg['mann_whitney_p_2sided'])}")
    print(f"  IC95% diff (pos - zero) views/dia = [{tg['welch_ci95_diff_a_menos_b'][0]:.2f}, {tg['welch_ci95_diff_a_menos_b'][1]:.2f}]")
    print()
    print("Confounder tempo (early vs late):")
    tt = findings["hipotese_principal"]["teste_tempo_early_vs_late"]
    print(f"  early n={tt['n_a']} media={f(tt['mean_a'])}  |  late n={tt['n_b']} media={f(tt['mean_b'])}")
    print(f"  Welch p={f(tt['welch_p_2sided'])}  Mann-Whitney p={f(tt['mann_whitney_p_2sided'])}")
    print()
    print("Estratificado (renovacao dentro de cada periodo):")
    for k in ("teste_estratificado_early", "teste_estratificado_late"):
        t = findings["hipotese_principal"][k]
        print(f"  {k}: n_a={t['n_a']} n_b={t['n_b']} mean_a={f(t['mean_a'])} mean_b={f(t['mean_b'])} welch_p={f(t['welch_p_2sided'])} mw_p={f(t['mann_whitney_p_2sided'])}")
    print()
    print("Correlacao:")
    print(f"  total_posts x total_views        r={f(r_pear)}  p={f(p_pear)}")
    print(f"  posts_ultimos_7d x total_views   r={f(r_pear2)} p={f(p_pear2)}")
    print(f"  indice_tempo x total_views       r={f(r_pear3)} p={f(p_pear3)}")
    print()
    print(f"OK: escritos {CSV_OUT_GROUPS} e {JSON_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

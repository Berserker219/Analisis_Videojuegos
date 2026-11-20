"""Figuras del reporte. Uso: python3 -I figuras.py <carpeta_csv> <salida_tablas> <salida_figuras>"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CSV, TAB, FIG = map(Path, sys.argv[1:4])
FIG.mkdir(parents=True, exist_ok=True)

SUP, TXT, TXT2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
AZUL, NARANJA = "#2a78d6", "#eb6834"
plt.rcParams.update({"figure.facecolor": SUP, "axes.facecolor": SUP, "savefig.facecolor": SUP,
                     "axes.edgecolor": GRID, "axes.labelcolor": TXT2, "xtick.color": TXT2, "ytick.color": TXT2,
                     "text.color": TXT, "font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 1, "axes.axisbelow": True})

j = pd.read_csv(CSV / "steam_juegos.csv")
g = pd.read_csv(CSV / "steam_generos.csv")
j = j[~j.es_software].copy()
j["gratuito"] = j.estado_precio == "gratuito"
j["pago"] = j.precio_ref_usd.fillna(0) > 0
M = j[j.grupo.isin(["aleatoria", "ambas"])].copy()
T = j[j.grupo.isin(["top", "ambas"])].copy()
R = j[j.grupo == "aleatoria"].copy()


def guardar(fig, nombre):
    fig.savefig(FIG / nombre, dpi=200, bbox_inches="tight")
    plt.close(fig)


def titulos(ax, t, sub=None):
    ax.set_title(t, loc="left", fontsize=13, fontweight="bold", color=TXT, pad=22 if sub else 10)
    if sub:
        ax.text(0, 1.03, sub, transform=ax.transAxes, fontsize=10, color=TXT2, va="bottom")


# F1 Lorenz de reseñas
xs = np.sort(M.resenas_total.values)
lor = pd.DataFrame({"pct_juegos": np.concatenate([[0], np.arange(1, len(xs) + 1) / len(xs)]), "pct_resenas": np.concatenate([[0], np.cumsum(xs) / xs.sum()])})
fig, ax = plt.subplots(figsize=(7, 5))
ax.plot(lor.pct_juegos * 100, lor.pct_resenas * 100, color=AZUL, lw=2)
ax.plot([0, 100], [0, 100], color=TXT2, lw=1, ls=(0, (1, 0)), alpha=.5)
ax.text(70, 76, "Reparto igualitario", color=TXT2, fontsize=10, rotation=34)
ax.scatter([90], [lor.loc[(lor.pct_juegos - .9).abs().idxmin(), "pct_resenas"] * 100], s=64, color=AZUL, edgecolor=SUP, linewidth=2, zorder=5)
ax.annotate("El 10% de juegos con más reseñas\nacumula el 95% del total", xy=(90, 5.4), xytext=(8, 55),
            fontsize=10, color=TXT, arrowprops=dict(arrowstyle="-", color=TXT2, lw=1))
ax.set_xlabel("% acumulado de juegos (de menos a más reseñas)")
ax.set_ylabel("% acumulado de reseñas")
ax.set_xlim(0, 100); ax.set_ylim(0, 100)
titulos(ax, "Casi todas las reseñas se concentran en muy pocos juegos",
        f"Curva de Lorenz de reseñas · muestra aleatoria, {len(M):,} juegos · Gini = 0.95")
guardar(fig, "f1_lorenz.png")

# F2 precios
cortes = [0, 4.99, 9.99, 19.99, 29.99, 49.99, 1000]
etq = ["≤ 4.99", "5–9.99", "10–19.99", "20–29.99", "30–49.99", "50+"]
dm = pd.cut(M[M.pago].precio_ref_usd, cortes, labels=etq).value_counts(normalize=True).reindex(etq) * 100
dt = pd.cut(T[T.pago].precio_ref_usd, cortes, labels=etq).value_counts(normalize=True).reindex(etq) * 100
fig, ax = plt.subplots(figsize=(8, 4.8))
x = np.arange(len(etq)); w = .36
b1 = ax.bar(x - w / 2 - .01, dm, w, color=AZUL, label="Muestra aleatoria (mercado)")
b2 = ax.bar(x + w / 2 + .01, dt, w, color=NARANJA, label="Top 2,000 por propietarios")
for b in list(b1) + list(b2):
    ax.text(b.get_x() + b.get_width() / 2, b.get_height() + .8, f"{b.get_height():.0f}%", ha="center", fontsize=9, color=TXT2)
ax.set_xticks(x); ax.set_xticklabels(etq); ax.set_xlabel("Precio en USD"); ax.set_ylabel("% de juegos de pago")
ax.grid(axis="x", visible=False); ax.legend(frameon=False, loc="upper right")
titulos(ax, "La mitad del mercado cuesta menos de \\$5 USD",
        f"Mediana: \\${M[M.pago].precio_ref_usd.median():.2f} en el mercado vs \\${T[T.pago].precio_ref_usd.median():.2f} en el top")
guardar(fig, "f2_precios.png")

# F3 por año: gratis y < 20k
pa = pd.read_csv(TAB / "t_por_anio.csv")
pa = pa[pa.anio_lanzamiento <= 2025]
fig, axs = plt.subplots(1, 2, figsize=(10, 4.2))
for ax, col, ttl in ((axs[0], "pct_gratis", "Juegos gratuitos"), (axs[1], "pct_bin0", "Juegos con menos de 20,000 propietarios")):
    ax.plot(pa.anio_lanzamiento, pa[col] * 100, color=AZUL, lw=2, marker="o", ms=5, mec=SUP, mew=2)
    ax.set_title(ttl, loc="left", fontsize=11, fontweight="bold")
    ax.set_ylabel("% de la muestra aleatoria"); ax.set_ylim(0, 100 if col == "pct_bin0" else 20)
    ax.set_xticks(range(2015, 2026, 2))
    ax.text(pa.anio_lanzamiento.iloc[-1], pa[col].iloc[-1] * 100 + (3 if col == "pct_bin0" else .8),
            f"{pa[col].iloc[-1]*100:.0f}%", ha="center", fontsize=9, color=TXT2)
fig.suptitle("Por año de lanzamiento: menos gratuitos y más juegos que no despegan", x=.01, ha="left", fontsize=13, fontweight="bold")
fig.tight_layout()
guardar(fig, "f3_por_anio.png")

# F4 aprobación por género
tg = pd.read_csv(TAB / "t_genero_aprobacion.csv").sort_values("wilson_mediana")
fig, ax = plt.subplots(figsize=(8, 4.8))
bars = ax.barh(tg.genero, tg.wilson_mediana, color=AZUL, height=.6)
for b, n in zip(bars, tg.n):
    ax.text(b.get_width() + .6, b.get_y() + b.get_height() / 2, f"{b.get_width():.0f}%  (n={n})", va="center", fontsize=9, color=TXT2)
ax.set_xlim(40, 90); ax.grid(axis="y", visible=False)
ax.set_xlabel("Mediana del límite inferior de Wilson (% de reseñas positivas)")
titulos(ax, "Los juegos masivos online son los peor valorados",
        "Juegos con ≥ 50 reseñas en la muestra aleatoria · un juego cuenta en cada uno de sus géneros")
guardar(fig, "f4_genero.png")

# F5 top vs resto
dif = pd.read_csv(TAB / "t_top_vs_resto.csv", index_col=0)
nombres = {"espanol": "Tiene español", "multijugador": "Multijugador", "logros_steam": "Logros de Steam",
           "compras_integradas": "Compras integradas", "autopublicado": "Autopublicado",
           "un_jugador": "Un jugador", "mac": "Mac", "linux": "Linux", "gratuito": "Gratuito", "early_access": "Early Access"}
dif = dif.loc[list(nombres)].sort_values("top")
fig, ax = plt.subplots(figsize=(8, 5.2))
y = np.arange(len(dif))
ax.hlines(y, dif.resto * 100, dif.top * 100, color=GRID, lw=3)
ax.scatter(dif.resto * 100, y, s=70, color=AZUL, edgecolor=SUP, linewidth=2, zorder=3, label="Resto (aleatoria fuera del top)")
ax.scatter(dif.top * 100, y, s=70, color=NARANJA, edgecolor=SUP, linewidth=2, zorder=3, label="Top 2,000")
ax.set_yticks(y); ax.set_yticklabels([nombres[i] for i in dif.index]); ax.grid(axis="y", visible=False)
ax.set_xlabel("% de juegos"); ax.set_xlim(0, 100); ax.legend(frameon=False, loc="lower right")
titulos(ax, "Los juegos más exitosos son multijugador y están traducidos",
        "Todas las diferencias son estadísticamente significativas (chi-cuadrada, p < 0.001)")
guardar(fig, "f5_top_vs_resto.png")

# F6 reseñas por n idiomas y español
mr = M[M.resenas_total > 0].copy()
mr["grp"] = pd.cut(mr.n_idiomas, [-1, 1, 5, 10, 200], labels=["0–1", "2–5", "6–10", "11+"])
t = mr.groupby(["grp", "espanol"], observed=True).resenas_total.agg(["size", "median"]).reset_index()
t = t[t.grp != "0–1"]
fig, ax = plt.subplots(figsize=(7.5, 4.6))
cats = ["2–5", "6–10", "11+"]; x = np.arange(3)
for k, (val, col, lab) in enumerate(((False, AZUL, "Sin español"), (True, NARANJA, "Con español"))):
    sub = t[t.espanol == val].set_index("grp").reindex(cats)
    sub.loc[sub["size"] < 30, "median"] = np.nan   # muestras muy chicas no se grafican
    bs = ax.bar(x + (k - .5) * .38, sub["median"], .36, color=col, label=lab)
    for b, n in zip(bs, sub["size"]):
        if pd.notna(b.get_height()):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.5, f"{b.get_height():.0f}\n(n={int(n)})", ha="center", fontsize=8.5, color=TXT2)
ax.set_xticks(x); ax.set_xticklabels(cats); ax.set_xlabel("Número de idiomas del juego"); ax.set_ylabel("Mediana de reseñas")
ax.set_ylim(0, 105); ax.grid(axis="x", visible=False); ax.legend(frameon=False, loc="upper left")
titulos(ax, "Con los mismos idiomas, el español no suma reseñas",
        "Lo que se asocia con más reseñas es traducir a muchos idiomas, no el español en sí")
guardar(fig, "f6_espanol.png")

# F7 tiempo por género (top)
gt = pd.read_csv(TAB / "t_genero_tiempo.csv").sort_values("median")
fig, ax = plt.subplots(figsize=(8, 4.8))
bars = ax.barh(gt.genero, gt["median"], color=AZUL, height=.6)
for b, n in zip(bars, gt["size"]):
    ax.text(b.get_width() + .1, b.get_y() + b.get_height() / 2, f"{b.get_width():.1f} h  (n={n})", va="center", fontsize=9, color=TXT2)
ax.set_xlim(0, 9); ax.grid(axis="y", visible=False); ax.set_xlabel("Mediana de horas jugadas (mediana por juego)")
titulos(ax, "Los RPG retienen más tiempo; los masivos online, menos",
        "Solo el top 2,000 (único grupo con tiempo de juego casi completo)")
guardar(fig, "f7_tiempo.png")
print("ok", sorted(p.name for p in FIG.iterdir()))
"""EDA Steam v1. Uso: python3 -I analisis.py <carpeta_con_csv> <carpeta_salida>"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.formula.api as smf

CSV, SAL = Path(sys.argv[1]), Path(sys.argv[2])
SAL.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 200, "display.max_columns", 40)

j = pd.read_csv(CSV / "steam_juegos.csv")
g = pd.read_csv(CSV / "steam_generos.csv")
j = j[~j.es_software].copy()
g = g[g.appid.isin(j.appid)]
j["gratuito"] = j.estado_precio == "gratuito"
j["pago"] = j.precio_ref_usd.fillna(0) > 0
j["bin0"] = j.propietarios_bajo == 0                     # 0 .. 20,000 propietarios
j["logres"] = np.log10(j.resenas_total + 1)
M = j[j.grupo.isin(["aleatoria", "ambas"])].copy()       # muestra aleatoria simple
T = j[j.grupo.isin(["top", "ambas"])].copy()             # top por propietarios
R = j[j.grupo == "aleatoria"].copy()                     # aleatoria fuera del top
print(f"sin software: {len(j)} | M={len(M)} T={len(T)} R={len(R)}")


def titulo(t):
    print("\n" + "=" * 8, t)


def gini(x):
    x = np.sort(np.asarray(x, float))
    n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1) @ x / (n * x.sum()))


# ---------- P1/P2 por año y precios
titulo("P1/P2 por año (muestra aleatoria M)")
por_anio = M.groupby("anio_lanzamiento").agg(
    n=("appid", "size"), pct_gratis=("gratuito", "mean"), pct_early=("early_access", "mean"),
    pct_bin0=("bin0", "mean"), mediana_resenas=("resenas_total", "median"),
    precio_mediano_pago=("precio_ref_usd", lambda s: s[s > 0].median()))
print(por_anio.round(3).to_string())
por_anio.to_csv(SAL / "t_por_anio.csv")

titulo("Precios (juegos de pago con precio de referencia)")
cortes = [0, 4.99, 9.99, 19.99, 29.99, 49.99, 1000]
etq = ["<=4.99", "5-9.99", "10-19.99", "20-29.99", "30-49.99", "50+"]
for nombre, d in (("M", M), ("T", T), ("R", R)):
    p = d[d.pago]
    dist = pd.cut(p.precio_ref_usd, cortes, labels=etq).value_counts(normalize=True).reindex(etq)
    print(nombre, f"n_pago={len(p)} mediana={p.precio_ref_usd.median():.2f} gratis={d.gratuito.mean():.3f}",
          (dist * 100).round(1).to_dict())
pm = M[M.pago]
print("con descuento activo (M, pago):", round((pm.descuento_pct.fillna(0) > 0).mean(), 3))
sub = M[(M.resenas_total >= 50) & M.pago]
rho, pval = stats.spearmanr(sub.precio_ref_usd, sub.aprobacion_wilson_pct)
print(f"Spearman precio vs aprobacion Wilson (M, >=50 res, n={len(sub)}): rho={rho:.3f} p={pval:.3g}")

# ---------- P3 aprobación por género
titulo("P3 aprobacion Wilson por genero (M, >=50 reseñas)")
base = M[M.resenas_total >= 50]
print("juegos M con >=50 reseñas:", len(base), f"({len(base)/len(M):.1%})")
gg = g.merge(base[["appid", "aprobacion_wilson_pct", "aprobacion_pct", "resenas_total"]], on="appid")
tg = gg.groupby("genero").agg(n=("appid", "size"), wilson_mediana=("aprobacion_wilson_pct", "median"),
                              aprob_mediana=("aprobacion_pct", "median"))
tg = tg[tg.n >= 40].sort_values("wilson_mediana", ascending=False)
print(tg.round(1).to_string())
tg.to_csv(SAL / "t_genero_aprobacion.csv")
grupos = [d.aprobacion_wilson_pct.values for _, d in gg[gg.genero.isin(tg.index)].groupby("genero")]
print("Kruskal-Wallis (generos solapados, uso descriptivo):", stats.kruskal(*grupos))
# comparacion sin solapamiento: juegos con un solo genero principal
unico = g.groupby("appid").genero.agg(list)
unico = unico[unico.str.len() == 1].str[0].rename("genero")
u = base.merge(unico, left_on="appid", right_index=True)
print("juegos con un solo genero:", len(u))
print(u.groupby("genero").aprobacion_wilson_pct.agg(["size", "median"]).query("size>=30").round(1).to_string())

# ---------- P4 concentración
titulo("P4 concentración (M)")
print("juegos en rango 0-20k propietarios:", f"{M.bin0.mean():.1%}")
rev = M.resenas_total.values
rng = np.random.default_rng(42)
bs = [gini(rng.choice(rev, len(rev))) for _ in range(500)]
print(f"Gini reseñas = {gini(rev):.3f}  IC95 bootstrap [{np.percentile(bs,2.5):.3f}, {np.percentile(bs,97.5):.3f}]")
bs2 = [gini(rng.choice(M.propietarios_medio.values, len(M))) for _ in range(500)]
print(f"Gini propietarios (punto medio de rango) = {gini(M.propietarios_medio):.3f} IC95 [{np.percentile(bs2,2.5):.3f}, {np.percentile(bs2,97.5):.3f}]")
orden = np.sort(rev)[::-1]
for q in (0.01, 0.05, 0.10, 0.20):
    k = max(1, int(round(len(orden) * q)))
    print(f"top {q:.0%} de juegos ({k}) concentra {orden[:k].sum()/orden.sum():.1%} de las reseñas")
xs = np.sort(rev)
lor = pd.DataFrame({"pct_juegos": np.arange(1, len(xs) + 1) / len(xs), "pct_resenas": np.cumsum(xs) / xs.sum()})
lor.iloc[::10].to_csv(SAL / "t_lorenz.csv", index=False)
print("mediana de reseñas:", M.resenas_total.median(), "| % con <10 reseñas:", f"{(M.resenas_total<10).mean():.1%}",
      "| % con >=1000:", f"{(M.resenas_total>=1000).mean():.1%}")
print("distribución de rangos de propietarios (M, %):")
print((M.propietarios_bajo.value_counts(normalize=True).sort_index() * 100).round(1).to_string())

# ---------- P5 factores de éxito
titulo("P5 top vs resto (T vs R) y modelo")
vars_bin = ["gratuito", "multijugador", "un_jugador", "espanol", "linux", "mac", "autopublicado",
            "early_access", "logros_steam", "compras_integradas"]
filas = []
for v in vars_bin:
    a, b = T[v].mean(), R[v].mean()
    chi = stats.chi2_contingency(pd.crosstab(pd.concat([T[v], R[v]]), ["T"] * len(T) + ["R"] * len(R)))
    filas.append((v, a, b, a - b, chi[1]))
dif = pd.DataFrame(filas, columns=["var", "top", "resto", "dif", "p"]).set_index("var")
print(dif.round(3).to_string())
dif.to_csv(SAL / "t_top_vs_resto.csv")
print("mediana idiomas T vs R:", T.n_idiomas.median(), R.n_idiomas.median(), "| precio mediano pago:",
      T[T.pago].precio_ref_usd.median(), R[R.pago].precio_ref_usd.median())
gen_dummies = ["Indie", "Action", "Adventure", "Casual", "Simulation", "Strategy", "RPG"]
for gen in gen_dummies:
    ids = set(g[g.genero == gen].appid)
    M["g_" + gen] = M.appid.isin(ids)
    ids_t = T.appid.isin(ids).mean(); ids_r = R.appid.isin(ids).mean()
    print(f"  genero {gen:11s} top={ids_t:.3f} resto={ids_r:.3f}")
D = M[M.precio_ref_usd.notna()].copy()
D["lprecio"] = np.log1p(D.precio_ref_usd)
D["lidiomas"] = np.log1p(D.n_idiomas)
D["tiene_dlc"] = D.n_dlc > 0
D["anios"] = D.antiguedad_anios
form = ("logres ~ gratuito + lprecio + early_access + multijugador + lidiomas + espanol + mac + linux + "
        "autopublicado + logros_steam + tiene_dlc + anios + " + " + ".join("g_" + x for x in gen_dummies))
for col in D.columns:
    if D[col].dtype == bool:
        D[col] = D[col].astype(int)
mod = smf.ols(form, data=D).fit(cov_type="HC3")
print(f"OLS log10(reseñas+1), n={int(mod.nobs)}, R2={mod.rsquared:.3f}")
tab = pd.DataFrame({"coef": mod.params, "ee": mod.bse, "p": mod.pvalues})
tab["efecto_x"] = 10 ** tab.coef
print(tab.round(3).to_string())
tab.to_csv(SAL / "t_modelo.csv")
cp = D.copy()
# el modelo con idiomas y español juntos: correlación
print("corr lidiomas-espanol:", round(D.lidiomas.corr(D.espanol), 3))

# ---------- P6 español y plataformas
titulo("P6 español y plataformas (M)")
print("M: espanol", round(M.espanol.mean(), 3), "latam", round(M.espanol_latam.mean(), 3),
      "audio", round(M.espanol_audio.mean(), 3), "| mac", round(M.mac.mean(), 3), "linux", round(M.linux.mean(), 3),
      "windows", round(M.windows.mean(), 3))
print("T: espanol", round(T.espanol.mean(), 3), "latam", round(T.espanol_latam.mean(), 3),
      "audio", round(T.espanol_audio.mean(), 3), "| mac", round(T.mac.mean(), 3), "linux", round(T.linux.mean(), 3))
print((M.groupby("anio_lanzamiento")[["espanol", "mac", "linux"]].mean() * 100).round(1).to_string())
mr = M[M.resenas_total > 0]
a, b = mr[mr.espanol].resenas_total, mr[~mr.espanol].resenas_total
print(f"mediana reseñas con español={a.median()} (n={len(a)}) sin={b.median()} (n={len(b)}) MWU p={stats.mannwhitneyu(a,b).pvalue:.3g}")
# comparación a igual numero de idiomas
mr = mr.assign(grp=pd.cut(mr.n_idiomas, [-1, 1, 5, 10, 200], labels=["0-1", "2-5", "6-10", "11+"]))
print(mr.groupby(["grp", "espanol"], observed=True).resenas_total.agg(["size", "median"]).to_string())
print("mediana idiomas por año:", M.groupby("anio_lanzamiento").n_idiomas.median().to_dict())

# ---------- P7/P8 ccu y tiempo de juego (solo juegos con dato)
titulo("P7/P8 ccu y tiempo de juego")
print("fracción con ccu>0 y tiempo>0 por grupo:")
print(j.groupby("grupo").apply(lambda d: pd.Series({"ccu>0": (d.ccu > 0).mean(), "tiempo>0": (d.tiempo_mediano_horas > 0).mean()})).round(3).to_string())
print("R (no top): tiempo>0 por >=50 reseñas:", round((R[R.resenas_total >= 50].tiempo_mediano_horas > 0).mean(), 3))
c = T[T.ccu > 0]
a, b = c[c.gratuito].ccu, c[c.pago].ccu
print(f"ccu mediana (T, ccu>0): gratis={a.median()} (n={len(a)}) pago={b.median()} (n={len(b)}) MWU p={stats.mannwhitneyu(a,b).pvalue:.3g}")
T["ccu_por_100k"] = T.ccu / (T.propietarios_medio / 1e5)
c = T[T.ccu > 0]
print("ccu por 100k propietarios (mediana): gratis", round(c[c.gratuito].ccu_por_100k.median(), 1), "pago", round(c[c.pago].ccu_por_100k.median(), 1))
tp = T[T.tiempo_mediano_horas > 0]
print("tiempo mediano de juego (horas), T con dato n=", len(tp))
print("gratis vs pago:", tp.groupby("gratuito").tiempo_mediano_horas.median().round(1).to_dict(),
      "MWU p=", f"{stats.mannwhitneyu(tp[tp.gratuito].tiempo_mediano_horas, tp[~tp.gratuito].tiempo_mediano_horas).pvalue:.3g}")
gt = g.merge(tp[["appid", "tiempo_mediano_horas"]], on="appid").groupby("genero").tiempo_mediano_horas.agg(["size", "median"])
gt = gt[gt["size"] >= 40].sort_values("median", ascending=False)
print(gt.round(1).to_string())
gt.to_csv(SAL / "t_genero_tiempo.csv")
mp = tp.copy()
mp["multi"] = mp.multijugador
print("multijugador vs no:", mp.groupby("multi").tiempo_mediano_horas.median().round(1).to_dict())

# ---------- Etiquetas
titulo("Etiquetas top5: T vs R")
def share(d):
    s = d.etiquetas_top5.dropna().str.split("; ").explode()
    return s.value_counts() / len(d)
st, sr = share(T), share(R)
et = pd.DataFrame({"top": st, "resto": sr}).fillna(0)
et["dif"] = et.top - et.resto
print(et.sort_values("dif", ascending=False).head(12).round(3).to_string())
print(et.sort_values("dif").head(12).round(3).to_string())
et.sort_values("dif", ascending=False).to_csv(SAL / "t_etiquetas.csv")
"""Construye la tabla de analisis a partir de los JSON crudos de collect.py.

Entrada (carpeta --raw, por defecto data/raw):
    muestra.csv            juegos elegidos y su grupo (top / aleatoria / ambas)
    store/<appid>.json     respuesta de la Steam Store API
    steamspy/<appid>.json  ficha de SteamSpy

Salida (carpeta --out, por defecto data/processed):
    steam_juegos.csv       una fila por juego, con variables ya limpias
    steam_etiquetas.csv    formato largo: appid, etiqueta, votos, proporcion
    steam_generos.csv      formato largo: appid, genero (generos de la Store, multi-etiqueta)

Notas de interpretacion (basadas en fichas reales):
  - SteamSpy 'price' = 0 NO significa gratuito: tambien aparece en juegos de pago sin precio
    disponible. Lo gratuito se decide con 'is_free' de la Store.
  - Store 'recommendations.total' NO coincide con el total de resenas de SteamSpy
    (en Team Fortress 2: 48,246 frente a 1,161,472). Para resenas se usa SteamSpy y la
    cifra de la Store se guarda aparte como 'recomendaciones_store'.
  - Tiempos de juego de SteamSpy: minutos (segun recuerdo), se convierten a horas.
  - La Store lista los generos en ORDEN ALFABETICO, asi que el "primer genero" no es el principal
    (en la muestra, 22 de 29 juegos daban 'Action'). Por eso no hay genero_principal: los generos
    van en formato largo (steam_generos.csv) y se analiza por pertenencia (multi-etiqueta).
  - precio_ref_usd: precio de la Store si existe; si no, el de SteamSpy cuando es > 0 (juegos de pago
    que la Store ya no vende, p. ej. Call of Duty MWII); si no, vacio. fuente_precio dice cual se uso.
"""

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd

from steam_parsers import (parse_languages, parse_owners, parse_price_spy,
                           parse_price_store, parse_release_date, tiene_espanol,
                           tiene_espanol_latam)

GENEROS_NO_PRINCIPALES = {"Free To Play", "Early Access"}
# Generos de la Store que marcan programas (no juegos). Se conservan en la tabla con es_software=True
# para poder excluirlos en el analisis.
GENEROS_SOFTWARE = {"Utilities", "Animation & Modeling", "Design & Illustration", "Photo Editing",
                    "Video Production", "Audio Production", "Software Training", "Web Publishing",
                    "Game Development", "Education", "Accounting"}


def leer_envoltorio(ruta):
    """Devuelve (capturado_en, respuesta) de un JSON de collect.py, o (None, None) si no existe."""
    if not ruta.exists():
        return None, None
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    return contenido.get("capturado_en"), contenido.get("respuesta")


def entero(valor, defecto=0):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return defecto


def wilson_inferior(positivas, total, z=1.96):
    """Limite inferior del intervalo de Wilson para la proporcion de reseñas positivas (en %).

    Con pocas reseñas el porcentaje simple es ruido; este limite penaliza esa incertidumbre.
    """
    if not total:
        return None
    p = positivas / total
    denominador = 1 + z * z / total
    centro = p + z * z / (2 * total)
    margen = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return round((centro - margen) / denominador * 100, 2)


def extraer_store(capturado, store):
    """Variables de una respuesta de la Store (ya validada como success=True)."""
    datos = store["data"]
    fecha = parse_release_date(datos.get("release_date"))
    inicial, final, descuento = parse_price_store(datos.get("price_overview"))
    es_gratis = bool(datos.get("is_free"))
    if es_gratis:
        estado_precio, precio = "gratuito", 0.0
    elif final is not None:
        estado_precio, precio = "de_pago", final
    else:
        estado_precio, precio = "sin_precio", None   # no gratuito y sin precio disponible

    generos = [g.get("description") for g in datos.get("genres") or [] if g.get("description")]
    principales = [g for g in generos if g not in GENEROS_NO_PRINCIPALES]
    categorias = {c.get("description") for c in datos.get("categories") or []}
    plataformas = datos.get("platforms") or {}
    idiomas, audio = parse_languages(datos.get("supported_languages"))
    desarrolladores = datos.get("developers") or []
    publicadores = datos.get("publishers") or []
    logros = (datos.get("achievements") or {}).get("total")
    metacritic = (datos.get("metacritic") or {}).get("score")
    fecha_captura = datetime.fromisoformat(capturado).replace(tzinfo=None) if capturado else None

    antiguedad = None
    if fecha and fecha_captura:
        antiguedad = round((fecha_captura - fecha).days / 365.25, 2)

    return {
        "fecha_lanzamiento": fecha.date().isoformat() if fecha else None,
        "anio_lanzamiento": fecha.year if fecha else None,
        "mes_lanzamiento": fecha.month if fecha else None,
        "antiguedad_anios": antiguedad,
        "estado_precio": estado_precio,
        "precio_usd": precio,
        "precio_inicial_usd": inicial,
        "descuento_pct": descuento,
        "edad_requerida": entero(datos.get("required_age")),
        "windows": bool(plataformas.get("windows")),
        "mac": bool(plataformas.get("mac")),
        "linux": bool(plataformas.get("linux")),
        "n_idiomas": len(idiomas),
        "n_idiomas_audio": len(audio),
        "espanol": tiene_espanol(idiomas),
        "espanol_latam": tiene_espanol_latam(idiomas),
        "espanol_audio": tiene_espanol(list(audio)),
        "generos_store": "; ".join(principales),
        "n_generos": len(principales),
        "es_software": any(g in GENEROS_SOFTWARE for g in generos),
        "early_access": "Early Access" in generos,
        "un_jugador": "Single-player" in categorias,
        "multijugador": "Multi-player" in categorias,
        "logros_steam": "Steam Achievements" in categorias,
        "compras_integradas": "In-App Purchases" in categorias,
        "n_logros": logros,
        "metacritic": metacritic,
        "n_dlc": len(datos.get("dlc") or []),
        "desarrollador": desarrolladores[0] if desarrolladores else None,
        "publicador": publicadores[0] if publicadores else None,
        "autopublicado": bool(desarrolladores) and desarrolladores == publicadores,
        "recomendaciones_store": (datos.get("recommendations") or {}).get("total"),
        "fecha_captura_store": fecha_captura.date().isoformat() if fecha_captura else None,
    }


def extraer_spy(ficha):
    """Variables de una ficha de SteamSpy y la lista de etiquetas (etiqueta, votos, proporcion)."""
    positivas, negativas = entero(ficha.get("positive")), entero(ficha.get("negative"))
    resenas = positivas + negativas
    bajo, alto, medio = parse_owners(ficha.get("owners"))
    etiquetas = ficha.get("tags")
    etiquetas = etiquetas if isinstance(etiquetas, dict) else {}
    total_votos = sum(etiquetas.values())
    ordenadas = sorted(etiquetas.items(), key=lambda kv: -kv[1])
    filas_etiquetas = [(t, v, v / total_votos) for t, v in ordenadas] if total_votos else []

    def horas(valor):
        return round(entero(valor) / 60, 2)

    return {
        "positivas": positivas,
        "negativas": negativas,
        "resenas_total": resenas,
        "aprobacion_pct": round(positivas / resenas * 100, 2) if resenas else None,
        "aprobacion_wilson_pct": wilson_inferior(positivas, resenas),
        "propietarios_bajo": bajo,
        "propietarios_alto": alto,
        "propietarios_medio": medio,
        "ccu": entero(ficha.get("ccu")),
        "tiempo_mediano_horas": horas(ficha.get("median_forever")),
        "tiempo_promedio_horas": horas(ficha.get("average_forever")),
        "precio_spy_usd": parse_price_spy(ficha.get("price")),
        "precio_inicial_spy_usd": parse_price_spy(ficha.get("initialprice")),
        "genero_spy": ficha.get("genre") or None,
        "n_etiquetas": len(etiquetas),
        "etiqueta_principal": ordenadas[0][0] if ordenadas else None,
        "etiquetas_top5": "; ".join(t for t, _ in ordenadas[:5]),
    }, filas_etiquetas


def precio_referencia(v_store, v_spy):
    """Precio unico para analizar: Store; si falta, SteamSpy si es > 0; si no, vacio."""
    if v_store["estado_precio"] in ("gratuito", "de_pago"):
        return {"precio_ref_usd": v_store["precio_usd"], "fuente_precio": "store"}
    spy = v_spy["precio_spy_usd"]
    if spy:
        return {"precio_ref_usd": spy, "fuente_precio": "steamspy"}
    return {"precio_ref_usd": None, "fuente_precio": "sin_dato"}


def construir(raw, out):
    raw, out = Path(raw), Path(out)
    with (raw / "muestra.csv").open(encoding="utf-8", newline="") as f:
        muestra = list(csv.DictReader(f))

    juegos, etiquetas, generos = [], [], []
    omitidos = {"sin_store": 0, "store_no_valido": 0, "sin_spy": 0}
    for fila in muestra:
        appid = fila["appid"]
        capturado, store = leer_envoltorio(raw / "store" / f"{appid}.json")
        _, ficha = leer_envoltorio(raw / "steamspy" / f"{appid}.json")
        if store is None:
            omitidos["sin_store"] += 1
            continue
        if not store.get("success"):
            omitidos["store_no_valido"] += 1
            continue
        if ficha is None:
            omitidos["sin_spy"] += 1
            continue
        variables_spy, filas_etiquetas = extraer_spy(ficha)
        variables_store = extraer_store(capturado, store)
        variables_store.update(precio_referencia(variables_store, variables_spy))
        juegos.append({
            "appid": int(appid),
            "nombre": fila["nombre"],
            "grupo": fila["grupo"],
            "posicion_propietarios": int(fila["posicion_propietarios"]),
            **variables_store,
            **variables_spy,
        })
        generos.extend((int(appid), g) for g in (variables_store["generos_store"] or "").split("; ") if g)
        etiquetas.extend((int(appid), t, v, round(p, 5)) for t, v, p in filas_etiquetas)

    out.mkdir(parents=True, exist_ok=True)
    tabla = pd.DataFrame(juegos)
    tabla.to_csv(out / "steam_juegos.csv", index=False, encoding="utf-8")
    pd.DataFrame(etiquetas, columns=["appid", "etiqueta", "votos", "proporcion"]).to_csv(
        out / "steam_etiquetas.csv", index=False, encoding="utf-8")
    pd.DataFrame(generos, columns=["appid", "genero"]).to_csv(
        out / "steam_generos.csv", index=False, encoding="utf-8")
    return tabla, omitidos, len(muestra)


def parsear(argv=None):
    p = argparse.ArgumentParser(description="Construye la tabla de analisis de Steam")
    p.add_argument("--raw", default="data/raw", help="carpeta con muestra.csv, store/ y steamspy/")
    p.add_argument("--out", default="data/processed", help="carpeta de salida")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = parsear()
    tabla, omitidos, total = construir(args.raw, args.out)
    print(f"Juegos en muestra.csv : {total:,}")
    print(f"Filas construidas     : {len(tabla):,}")
    print(f"Omitidos              : {omitidos}")
    if len(tabla):
        print("\nGrupos:")
        print(tabla["grupo"].value_counts().to_string())
        nulos = (tabla.isna().mean() * 100).round(1)
        nulos = nulos[nulos > 0].sort_values(ascending=False)
        print("\n% de valores vacios por columna (solo las que tienen):")
        print(nulos.to_string() if len(nulos) else "ninguna")
        print("\nEstado de precio por grupo:")
        print(pd.crosstab(tabla["grupo"], tabla["estado_precio"]).to_string())
        print("\nFuente del precio de referencia:", tabla["fuente_precio"].value_counts().to_dict())
        print(f"Software (no juegos)  : {int(tabla['es_software'].sum()):,}")
        print(f"Early Access          : {tabla['early_access'].mean():.1%}")
        print(f"Sin resenas           : {int((tabla['resenas_total'] == 0).sum()):,}")
        print(f"Capturas de la Store  : {tabla['fecha_captura_store'].min()} a {tabla['fecha_captura_store'].max()}")
        print("\nJuegos por año de lanzamiento y grupo:")
        print(pd.crosstab(tabla["anio_lanzamiento"], tabla["grupo"]).to_string())
        print(f"\nGuardado en {Path(args.out) / 'steam_juegos.csv'}")
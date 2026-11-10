"""Diagnostico de la lista de SteamSpy ya descargada (data/raw/steamspy_all).

Responde: ¿esta completa?, ¿viene ordenada por propietarios?, ¿que tan confiables son los
campos?, ¿como queda el grupo top? Sirve para decidir que preguntas son viables.

Uso:  py revisar_lista.py            (busca en data/raw)
      py revisar_lista.py data/prueba
Va en la misma carpeta que steam_parsers.py. Encuentra las paginas aunque esten en subcarpetas.
"""

import json
import re
import sys
from pathlib import Path

import pandas as pd

from steam_parsers import parse_owners


def orden_natural(ruta):
    """Ordena pagina_2 antes que pagina_10."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", ruta.name)]


def leer_pagina(ruta):
    """Devuelve (capturado_en, {appid: juego}) o None si el archivo no parece una pagina de SteamSpy."""
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    capturado = ""
    if isinstance(contenido, dict) and "respuesta" in contenido:   # formato de collect.py
        capturado = contenido.get("capturado_en", "")
        contenido = contenido["respuesta"]
    if not isinstance(contenido, dict) or not contenido:
        return None
    primero = next(iter(contenido.values()))
    if not isinstance(primero, dict) or "owners" not in primero:
        return None
    return capturado, contenido


def encontrar_paginas(carpeta):
    """Busca las paginas donde esten: pagina_*.json en cualquier subcarpeta o *.json sueltos."""
    carpeta = Path(carpeta)
    archivos = sorted(carpeta.rglob("pagina_*.json"), key=orden_natural)
    if not archivos:
        archivos = sorted(carpeta.glob("*.json"), key=orden_natural)
    paginas = []
    for archivo in archivos:
        pagina = leer_pagina(archivo)
        if pagina:
            paginas.append((archivo, pagina))
    return paginas


def cargar(carpeta):
    paginas = encontrar_paginas(carpeta)
    filas, capturas = [], []
    for n, (archivo, (capturado, juegos)) in enumerate(paginas):
        capturas.append(capturado)
        for juego in juegos.values():
            fila = dict(juego)
            fila["pagina"] = n
            filas.append(fila)
    return pd.DataFrame(filas), [a for a, _ in paginas], capturas


def porcentaje(serie):
    return f"{serie.mean():.1%}"


def main(carpeta="data/raw"):
    df, archivos, capturas = cargar(carpeta)
    if df.empty:
        print(f"No encontre paginas de SteamSpy dentro de '{carpeta}'.")
        print("Busque pagina_*.json en cualquier subcarpeta y *.json sueltos que contengan el campo 'owners'.")
        print("Ejecuta:  dir data\\raw   y pegame los nombres de los archivos y carpetas.")
        return
    marcadores = list(Path(carpeta).rglob("fin_de_lista.txt"))
    marcador = marcadores[0] if marcadores else Path("no_existe")

    print("=== 1. Resumen ===")
    print(f"Paginas encontradas : {len(archivos)}  (carpeta: {archivos[0].parent}; primera: {archivos[0].name}; ultima: {archivos[-1].name})")
    print(f"Lista completa      : {'si (fin_de_lista.txt = ' + marcador.read_text().strip() + ')' if marcador.exists() else 'NO (falta fin_de_lista.txt)'}")
    print(f"Juegos (filas)      : {len(df):,}   unicos: {df['appid'].nunique():,}")
    fechas = [c for c in capturas if c]
    print(f"Capturas            : {min(fechas)} a {max(fechas)}" if fechas else "Capturas            : (sin fecha en los archivos)")

    numericas = ["positive", "negative", "userscore", "average_forever", "average_2weeks",
                 "median_forever", "median_2weeks", "price", "initialprice", "discount", "ccu"]
    for columna in numericas + ["owners", "name", "score_rank"]:
        if columna not in df.columns:
            print(f"AVISO: los archivos no traen la columna '{columna}'")
            df[columna] = None
    for columna in numericas:
        df[columna] = pd.to_numeric(df[columna], errors="coerce")
    df[["bajo", "alto", "medio"]] = df["owners"].apply(lambda t: pd.Series(parse_owners(t)))
    df["resenas"] = df["positive"].fillna(0) + df["negative"].fillna(0)

    print("\n=== 2. ¿Viene ordenada por propietarios? ===")
    medio = df["medio"].fillna(0).reset_index(drop=True)
    subidas = int((medio.diff() > 0).sum())
    print(f"Veces que el rango SUBE respecto al juego anterior: {subidas:,} de {len(df) - 1:,}")
    print("(si estuviera ordenada de mayor a menor, esto seria 0 o casi 0)")
    muestra = [p for p in (0, 1, 2, 10, 20, 40, 60, len(archivos) - 1) if p < len(archivos)]
    por_pagina = df.groupby("pagina")["medio"].median()
    print("Propietarios (punto medio, mediana) por pagina:")
    print(por_pagina.loc[sorted(set(muestra))].round(0).astype("Int64").to_string())

    print("\n=== 3. Rangos de propietarios ===")
    rangos = (df.groupby("owners").agg(juegos=("appid", "size"), bajo=("bajo", "first"))
              .sort_values("bajo", ascending=False))
    rangos["%"] = (rangos["juegos"] / len(df) * 100).round(1)
    print(rangos[["juegos", "%"]].to_string())

    print("\n=== 4. Calidad por campo (% de juegos) ===")
    calidad = {
        "sin resenas (positive+negative = 0)": df["resenas"] == 0,
        "propietarios no interpretables": df["medio"].isna(),
        "price = 0": df["price"] == 0,
        "initialprice = 0": df["initialprice"] == 0,
        "average_forever = 0": df["average_forever"] == 0,
        "median_forever = 0": df["median_forever"] == 0,
        "userscore = 0": df["userscore"] == 0,
        "score_rank vacio": df["score_rank"].astype(str).str.strip().isin(["", "nan", "None"]),
        "ccu = 0": df["ccu"] == 0,
        "nombre vacio": df["name"].fillna("").str.strip() == "",
    }
    for nombre, mascara in calidad.items():
        print(f"{nombre:40s} {porcentaje(mascara)}")

    print("\n=== 5. Grupo top (2,000 con mas propietarios) ===")
    orden = df.drop_duplicates("appid").sort_values(["medio", "resenas"], ascending=[False, False])
    corte = orden.iloc[:2000]
    print(f"Juegos con la cuota llena : {len(corte):,}")
    if len(orden) >= 2000:
        print(f"Rango del juego #2000     : {orden.iloc[1999]['owners']}")
        print(f"Rango del juego #2001     : {orden.iloc[2000]['owners'] if len(orden) > 2000 else '-'}")
        empate = int((orden["owners"] == orden.iloc[1999]["owners"]).sum())
        print(f"Juegos en ese mismo rango : {empate:,}  (el corte se decide por numero de resenas)")
    print("\nPrimeros 5 por propietarios:")
    print(orden.head(5)[["appid", "name", "owners", "resenas"]].to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw")
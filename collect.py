"""Recoleccion de datos de Steam (VERSION SENCILLA: SteamSpy + Steam Store API).

Que hace, en orden:
  1. Descarga la lista de juegos de SteamSpy (request=all, 1000 juegos por pagina).
     Es el universo de esta version; se ordena por propietarios al cargarla.
  2. Arma dos grupos de juegos, consultando la Store API para validar cada candidato:
       - "top":       los N_TOP con mas propietarios
       - "aleatoria": N_ALEATORIA elegidos al azar (semilla fija, reproducible)
     Un juego es valido si: la Store lo encuentra, type == "game" y se lanzo entre
     FECHA_MIN y FECHA_MAX. Se sigue revisando candidatos hasta llenar cada cuota.
  3. Para cada juego valido guarda tambien su ficha de SteamSpy (etiquetas, idiomas, tiempo de juego...).

Todo se guarda CRUDO, con fecha de captura, en data/raw/. Se puede interrumpir (Ctrl+C) y
volver a correr: lo ya descargado no se vuelve a pedir.

Salida principal: data/raw/muestra.csv (appid, nombre, grupo, posicion_propietarios).
La limpieza (fechas, precios, idiomas...) se hace despues con steam_parsers.py.

Uso minimo para probar (descarga 2 paginas de la lista y pocos juegos):
    py collect.py --dir data/prueba --max-paginas 2 --lista-parcial --n-top 5 --n-aleatoria 10
Uso completo:
    py collect.py
"""

import argparse
import csv
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from steam_parsers import parse_owners, parse_release_date

SPY_URL = "https://steamspy.com/api.php"
STORE_URL = "https://store.steampowered.com/api/appdetails"

FECHA_MIN = datetime(2015, 1, 1)
FECHA_MAX = datetime(2026, 12, 31)
MAX_FALLOS_SEGUIDOS = 5
CABECERAS = {"User-Agent": "steam-market-analysis/0.1 (proyecto de portafolio)"}


class Detenido(Exception):
    """Parada controlada: limite de llamadas alcanzado o demasiados fallos seguidos."""


class Limitador:
    """Garantiza un intervalo minimo entre llamadas al mismo servidor."""

    def __init__(self, intervalo):
        self.intervalo = intervalo
        self.ultimo = None

    def esperar(self):
        if self.ultimo is not None:
            falta = self.intervalo - (time.monotonic() - self.ultimo)
            if falta > 0:
                time.sleep(falta)
        self.ultimo = time.monotonic()


def guardar_json(ruta, respuesta):
    """Guarda la respuesta cruda junto con la fecha de captura (escritura segura)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    envoltorio = {
        "capturado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "respuesta": respuesta,
    }
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(envoltorio, ensure_ascii=False), encoding="utf-8")
    temporal.replace(ruta)


def leer_json(ruta):
    return json.loads(ruta.read_text(encoding="utf-8"))["respuesta"]


def entero(valor):
    """Convierte a entero un valor que puede venir como numero, texto o vacio."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0


def cumple_criterios(store):
    """True si la respuesta de la Store describe un juego lanzado dentro del periodo."""
    if not store or not store.get("success"):
        return False
    datos = store.get("data") or {}
    if datos.get("type") != "game":
        return False
    fecha = parse_release_date(datos.get("release_date"))
    return fecha is not None and FECHA_MIN <= fecha <= FECHA_MAX


class Recolector:
    def __init__(self, carpeta, pausa_lista, pausa_store, pausa_spy,
                 max_llamadas=None, sesion=None):
        self.carpeta = Path(carpeta)
        self.sesion = sesion or requests.Session()
        self.sesion.headers.update(CABECERAS)
        self.lim_lista = Limitador(pausa_lista)
        self.lim_store = Limitador(pausa_store)
        self.lim_spy = Limitador(pausa_spy)
        self.max_llamadas = max_llamadas
        self.llamadas = 0
        self.fallos_seguidos = 0

    # ---------- red ----------
    def pedir_json(self, url, params, limitador, intentos=4):
        """GET con espera entre llamadas y reintentos. Devuelve el JSON o None si falla."""
        for intento in range(1, intentos + 1):
            if self.max_llamadas is not None and self.llamadas >= self.max_llamadas:
                raise Detenido(f"se alcanzo el limite de {self.max_llamadas} llamadas")
            limitador.esperar()
            self.llamadas += 1
            try:
                r = self.sesion.get(url, params=params, timeout=30)
            except requests.RequestException as error:
                print(f"  error de red ({error.__class__.__name__}); intento {intento}/{intentos}")
                if intento < intentos:
                    time.sleep(5 * intento)
                continue
            if r.status_code == 200:
                try:
                    datos = r.json()
                except ValueError:
                    datos = None
                if datos is not None:
                    self.fallos_seguidos = 0
                    return datos
                print("  respuesta vacia o no valida")
                if intento < intentos:
                    time.sleep(5 * intento)
            elif r.status_code in (429, 500, 502, 503, 504):
                print(f"  HTTP {r.status_code}")
                if intento < intentos:           # no se espera despues del ultimo intento
                    espera = 20 * intento
                    print(f"  reintento en {espera} s")
                    time.sleep(espera)
            else:
                print(f"  HTTP {r.status_code}")
                break
        self.fallos_seguidos += 1
        if self.fallos_seguidos >= MAX_FALLOS_SEGUIDOS:
            raise Detenido("demasiados fallos seguidos; se detiene para no insistir ante un bloqueo")
        return None

    # ---------- 1. lista de SteamSpy ----------
    def descargar_lista(self, max_paginas):
        """Descarga las paginas de request=all. True si la lista quedo completa."""
        carpeta = self.carpeta / "steamspy_all"
        fin = carpeta / "fin_de_lista.txt"
        if fin.exists():
            return True
        for pagina in range(max_paginas):
            archivo = carpeta / f"pagina_{pagina:03d}.json"
            if archivo.exists():
                continue
            print(f"Lista de SteamSpy, pagina {pagina}...")
            datos = self.pedir_json(SPY_URL, {"request": "all", "page": pagina}, self.lim_lista)
            if datos is None:
                return False
            if not datos:  # pagina vacia: se acabo la lista
                carpeta.mkdir(parents=True, exist_ok=True)
                fin.write_text(str(pagina), encoding="utf-8")
                print(f"Lista completa: {pagina} paginas.")
                return True
            guardar_json(archivo, datos)
        return False

    def cargar_universo(self):
        """Juegos de la lista, sin repetidos, ordenados por propietarios estimados (mayor a menor).

        El orden se calcula aqui y no depende de como entregue SteamSpy las paginas.
        Como los propietarios vienen en rangos hay muchos empates; se desempata por
        numero de resenas (positivas + negativas).
        """
        universo, vistos = [], set()
        for archivo in sorted((self.carpeta / "steamspy_all").glob("pagina_*.json")):
            for clave, juego in leer_json(archivo).items():
                appid = int(clave)
                if appid in vistos:
                    continue
                vistos.add(appid)
                _, _, medio = parse_owners(juego.get("owners"))
                resenas = entero(juego.get("positive")) + entero(juego.get("negative"))
                universo.append({"appid": appid, "nombre": juego.get("name") or "",
                                 "propietarios": medio or 0, "resenas": resenas})
        universo.sort(key=lambda j: (-j["propietarios"], -j["resenas"]))
        return universo

    # ---------- 2. validacion y fichas ----------
    def datos_store(self, appid):
        archivo = self.carpeta / "store" / f"{appid}.json"
        if archivo.exists():
            return leer_json(archivo)
        datos = self.pedir_json(
            STORE_URL, {"appids": appid, "cc": "us", "l": "english"}, self.lim_store)
        if not isinstance(datos, dict):
            return None
        respuesta = datos.get(str(appid)) or {"success": False}
        guardar_json(archivo, respuesta)
        return respuesta

    def datos_spy(self, appid):
        archivo = self.carpeta / "steamspy" / f"{appid}.json"
        if archivo.exists():
            return leer_json(archivo)
        datos = self.pedir_json(
            SPY_URL, {"request": "appdetails", "appid": appid}, self.lim_spy)
        if not isinstance(datos, dict):
            return None
        guardar_json(archivo, datos)
        return datos

    def evaluar(self, appid):
        """'valido', 'invalido' o 'fallo' (no se pudo consultar; se reintenta en otra corrida)."""
        store = self.datos_store(appid)
        if store is None:
            return "fallo"
        if not cumple_criterios(store):
            return "invalido"
        if self.datos_spy(appid) is None:
            return "fallo"
        return "valido"

    def llenar_cuota(self, nombre, candidatos, cuota):
        elegidos, revisados = [], 0
        for appid in candidatos:
            if len(elegidos) >= cuota:
                break
            revisados += 1
            if self.evaluar(appid) == "valido":
                elegidos.append(appid)
            if revisados % 50 == 0:
                print(f"  [{nombre}] revisados {revisados}, validos {len(elegidos)}/{cuota}")
        print(f"[{nombre}] revisados {revisados}, validos {len(elegidos)}/{cuota}")
        if len(elegidos) < cuota:
            print(f"AVISO: el grupo '{nombre}' quedo con {len(elegidos)} de {cuota} juegos")
        return elegidos


def escribir_muestra(ruta, universo, top, aleatoria):
    nombres = {j["appid"]: j["nombre"] for j in universo}
    posicion = {j["appid"]: i + 1 for i, j in enumerate(universo)}
    en_top, en_aleatoria = set(top), set(aleatoria)
    with ruta.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(["appid", "nombre", "grupo", "posicion_propietarios"])
        for appid in sorted(en_top | en_aleatoria, key=posicion.get):
            if appid in en_top and appid in en_aleatoria:
                grupo = "ambas"
            else:
                grupo = "top" if appid in en_top else "aleatoria"
            escritor.writerow([appid, nombres[appid], grupo, posicion[appid]])


def parsear(argv=None):
    p = argparse.ArgumentParser(description="Recoleccion de datos de Steam (SteamSpy + Store API)")
    p.add_argument("--dir", default="data/raw", help="carpeta de salida (por defecto data/raw)")
    p.add_argument("--n-top", type=int, default=2000, help="juegos del grupo top")
    p.add_argument("--n-aleatoria", type=int, default=5000, help="juegos del grupo aleatorio")
    p.add_argument("--semilla", type=int, default=42, help="semilla del muestreo aleatorio")
    p.add_argument("--max-paginas", type=int, default=300, help="tope de paginas de la lista")
    p.add_argument("--lista-parcial", action="store_true",
                   help="usar la lista aunque no este completa (solo para pruebas)")
    p.add_argument("--max-llamadas", type=int, default=None,
                   help="detenerse tras N llamadas de red (para trabajar por lotes)")
    p.add_argument("--pausa-lista", type=float, default=61.0, help="segundos entre paginas de la lista")
    p.add_argument("--pausa-store", type=float, default=1.5, help="segundos entre llamadas a la Store")
    p.add_argument("--pausa-spy", type=float, default=1.5, help="segundos entre fichas de SteamSpy")
    return p.parse_args(argv)


def ejecutar(args, sesion=None):
    r = Recolector(args.dir, args.pausa_lista, args.pausa_store, args.pausa_spy,
                   args.max_llamadas, sesion)
    try:
        completa = r.descargar_lista(args.max_paginas)
        if not completa and not args.lista_parcial:
            print("La lista de SteamSpy no esta completa. Vuelve a correr el script para continuar.")
            return 1
        universo = r.cargar_universo()
        if not completa:
            print("AVISO: lista parcial, solo para pruebas.")
        print(f"Universo: {len(universo)} juegos de SteamSpy")
        ids = [j["appid"] for j in universo]
        top = r.llenar_cuota("top", ids, args.n_top)
        barajados = ids[:]
        random.Random(args.semilla).shuffle(barajados)
        aleatoria = r.llenar_cuota("aleatoria", barajados, args.n_aleatoria)
    except Detenido as motivo:
        print(f"\nDetenido: {motivo}. Lo descargado se conserva; vuelve a correr para continuar.")
        return 2
    except KeyboardInterrupt:
        print("\nInterrumpido. Lo descargado se conserva; vuelve a correr para continuar.")
        return 130
    ruta = Path(args.dir) / "muestra.csv"
    escribir_muestra(ruta, universo, top, aleatoria)
    print(f"Listo: {len(set(top) | set(aleatoria))} juegos en {ruta} ({r.llamadas} llamadas en esta corrida)")
    return 0


if __name__ == "__main__":
    sys.exit(ejecutar(parsear()))
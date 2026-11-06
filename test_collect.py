"""Pruebas de collect.py con respuestas simuladas (sin red). Ejecutar: py test_collect.py"""

import csv
import tempfile
from pathlib import Path

import requests

import collect

collect.time.sleep = lambda segundos: None   # las pruebas no esperan

# --- universo falso: 25 juegos (ids 1001..1025) en paginas de 10; la pagina 3 viene vacia ---
IDS = list(range(1001, 1026))
PAGINAS = {
    0: {str(i): {"appid": i, "name": f"Juego {i}"} for i in IDS[0:10]},
    1: {str(i): {"appid": i, "name": f"Juego {i}"} for i in IDS[10:20]},
    2: {str(i): {"appid": i, "name": f"Juego {i}"} for i in IDS[20:25]},
}


def ficha_store(appid):
    if appid in (1003, 1007):                      # la Store no lo encuentra
        return {"success": False}
    tipo = "dlc" if appid % 5 == 0 else "game"     # 1005, 1010... son DLC
    fecha = {"coming_soon": False, "date": "Jun 5, 2019"}
    if appid in (1002, 1012):                      # anteriores al periodo
        fecha = {"coming_soon": False, "date": "Mar 3, 2012"}
    if appid == 1004:                              # aun no sale
        fecha = {"coming_soon": True, "date": "Coming soon"}
    return {"success": True, "data": {"type": tipo, "release_date": fecha}}


class Respuesta:
    def __init__(self, estado=200, datos=None):
        self.status_code, self._datos = estado, datos

    def json(self):
        if self._datos is None:
            raise ValueError("sin JSON")
        return self._datos


class SesionFalsa:
    def __init__(self, store_estado=200):
        self.headers, self.llamadas, self.store_estado = {}, [], store_estado

    def get(self, url, params=None, timeout=None):
        self.llamadas.append((url, dict(params)))
        if url == collect.SPY_URL and params["request"] == "all":
            return Respuesta(200, PAGINAS.get(params["page"], {}))
        if url == collect.SPY_URL:
            return Respuesta(200, {"appid": params["appid"], "tags": {"RPG": 10}})
        if self.store_estado != 200:
            return Respuesta(self.store_estado)
        appid = int(params["appids"])
        return Respuesta(200, {str(appid): ficha_store(appid)})


def correr(carpeta, sesion, *extra):
    args = collect.parsear([
        "--dir", str(carpeta), "--pausa-lista", "0", "--pausa-store", "0", "--pausa-spy", "0", *extra])
    return collect.ejecutar(args, sesion)


def leer_muestra(carpeta):
    with (Path(carpeta) / "muestra.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_flujo_completo_y_reanudacion():
    with tempfile.TemporaryDirectory() as tmp:
        s1 = SesionFalsa()
        assert correr(tmp, s1, "--n-top", "3", "--n-aleatoria", "6") == 0
        filas = leer_muestra(tmp)
        top = [int(f["appid"]) for f in filas if f["grupo"] in ("top", "ambas")]
        ale = [int(f["appid"]) for f in filas if f["grupo"] in ("aleatoria", "ambas")]
        assert top == [1001, 1006, 1008], top             # los 3 primeros validos por propietarios
        assert len(ale) == 6, ale
        for appid in top + ale:                            # todos cumplen los criterios
            assert collect.cumple_criterios(ficha_store(appid))
        assert not {1002, 1003, 1004, 1005, 1007, 1012} & set(top + ale)
        assert (Path(tmp) / "steamspy" / "1001.json").exists()
        s2 = SesionFalsa()                                 # segunda corrida: todo en cache
        assert correr(tmp, s2, "--n-top", "3", "--n-aleatoria", "6") == 0
        assert len(s2.llamadas) == 0, len(s2.llamadas)
        assert leer_muestra(tmp) == filas                  # mismo resultado (semilla fija)


def test_limite_de_llamadas_y_continuacion():
    with tempfile.TemporaryDirectory() as tmp:
        assert correr(tmp, SesionFalsa(), "--max-llamadas", "6", "--n-top", "3", "--n-aleatoria", "6") == 2
        assert correr(tmp, SesionFalsa(), "--n-top", "3", "--n-aleatoria", "6") == 0
        assert len(leer_muestra(tmp)) >= 6


def test_demasiados_fallos_detiene():
    with tempfile.TemporaryDirectory() as tmp:
        assert correr(tmp, SesionFalsa(store_estado=500), "--n-top", "3", "--n-aleatoria", "6") == 2
        assert not (Path(tmp) / "store").exists() or not list((Path(tmp) / "store").glob("*.json"))


def test_lista_parcial():
    with tempfile.TemporaryDirectory() as tmp:
        assert correr(tmp, SesionFalsa(), "--max-paginas", "1", "--n-top", "2", "--n-aleatoria", "2") == 1
        assert correr(tmp, SesionFalsa(), "--max-paginas", "1", "--lista-parcial",
                      "--n-top", "2", "--n-aleatoria", "2") == 0


def test_reintento_ante_429():
    class Sesion429(SesionFalsa):
        def get(self, url, params=None, timeout=None):
            if not self.llamadas:
                self.llamadas.append("429")
                return Respuesta(429)
            return super().get(url, params, timeout)

    r = collect.Recolector("x", 0, 0, 0, sesion=Sesion429())
    assert r.pedir_json(collect.SPY_URL, {"request": "all", "page": 0}, r.lim_lista) == PAGINAS[0]


def test_error_de_red_se_reintenta():
    class SesionRed(SesionFalsa):
        def get(self, url, params=None, timeout=None):
            if not self.llamadas:
                self.llamadas.append("red")
                raise requests.ConnectionError("sin red")
            return super().get(url, params, timeout)

    r = collect.Recolector("x", 0, 0, 0, sesion=SesionRed())
    assert r.pedir_json(collect.SPY_URL, {"request": "all", "page": 0}, r.lim_lista) == PAGINAS[0]


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for prueba in pruebas:
        prueba()
        print("OK ", prueba.__name__)
    print(f"\n{len(pruebas)} pruebas pasaron")
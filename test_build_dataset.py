"""Pruebas de build_dataset.py con fichas recortadas de datos reales. Ejecutar: py test_build_dataset.py"""

import csv
import json
import tempfile
from pathlib import Path

import build_dataset as b

CAPTURA = "2026-11-11T22:30:49+00:00"

# Recortado de la respuesta real de la Store para Team Fortress 2 (appid 440)
STORE_TF2 = {"success": True, "data": {
    "type": "game", "name": "Team Fortress 2", "steam_appid": 440, "required_age": 0, "is_free": True,
    "dlc": [629330],
    "supported_languages": "English<strong>*</strong>, Danish, Spanish - Spain, Spanish - Latin America"
                           "<br><strong>*</strong>languages with full audio support",
    "platforms": {"windows": True, "mac": False, "linux": True},
    "metacritic": {"score": 92},
    "categories": [{"id": 1, "description": "Multi-player"}, {"id": 22, "description": "Steam Achievements"}],
    "genres": [{"id": "1", "description": "Action"}, {"id": "37", "description": "Free To Play"}],
    "developers": ["Valve"], "publishers": ["Valve"],
    "recommendations": {"total": 48246}, "achievements": {"total": 520},
    "release_date": {"coming_soon": False, "date": "Oct 10, 2007"}}}

# Recortado de la ficha real de SteamSpy para Grand Theft Auto V Legacy (appid 271590)
SPY_GTA = {"appid": 271590, "name": "Grand Theft Auto V Legacy", "positive": 1739980, "negative": 250576,
           "owners": "50,000,000 .. 100,000,000", "average_forever": 15695, "median_forever": 5629,
           "price": "0", "initialprice": "0", "ccu": 60092, "genre": "Action, Adventure",
           "languages": "English, Spanish - Latin America",
           "tags": {"Open World": 32676, "Action": 23557, "Multiplayer": 21773}}


def guardar(ruta, respuesta):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"capturado_en": CAPTURA, "respuesta": respuesta}), encoding="utf-8")


def test_wilson():
    assert b.wilson_inferior(0, 0) is None
    chico = b.wilson_inferior(9, 10)        # 90% con 10 reseñas: debe penalizarse mucho
    grande = b.wilson_inferior(900, 1000)   # 90% con 1000 reseñas: casi no se penaliza
    assert chico < 65 < 85 < grande < 90, (chico, grande)


def test_extraer_store():
    v = b.extraer_store(CAPTURA, STORE_TF2)
    assert v["fecha_lanzamiento"] == "2007-10-10" and v["anio_lanzamiento"] == 2007
    assert v["estado_precio"] == "gratuito" and v["precio_usd"] == 0.0
    assert v["generos_store"] == "Action" and v["n_generos"] == 1        # 'Free To Play' no cuenta
    assert v["es_software"] is False
    assert v["espanol"] and v["espanol_latam"] and not v["espanol_audio"]
    assert v["n_idiomas"] == 4 and v["n_idiomas_audio"] == 1             # la nota al pie no es un idioma
    assert v["multijugador"] and v["logros_steam"] and not v["un_jugador"]
    assert v["autopublicado"] and v["n_dlc"] == 1 and v["n_logros"] == 520 and v["metacritic"] == 92
    assert v["antiguedad_anios"] == 19.09


def test_precio_de_pago_y_sin_precio():
    pago = json.loads(json.dumps(STORE_TF2))
    pago["data"].update(is_free=False, price_overview={"initial": 5999, "final": 5999, "discount_percent": 0})
    v = b.extraer_store(CAPTURA, pago)
    assert v["estado_precio"] == "de_pago" and v["precio_usd"] == 59.99 and v["descuento_pct"] == 0
    sin = json.loads(json.dumps(STORE_TF2))
    sin["data"]["is_free"] = False          # no gratuito y sin price_overview: juego no disponible
    v = b.extraer_store(CAPTURA, sin)
    assert v["estado_precio"] == "sin_precio" and v["precio_usd"] is None


def test_software_y_precio_referencia():
    sw = json.loads(json.dumps(STORE_TF2))
    sw["data"]["genres"] = [{"id": "1", "description": "Utilities"}]
    assert b.extraer_store(CAPTURA, sw)["es_software"] is True
    sin = {"estado_precio": "sin_precio", "precio_usd": None}
    assert b.precio_referencia(sin, {"precio_spy_usd": 38.49}) == {"precio_ref_usd": 38.49, "fuente_precio": "steamspy"}
    assert b.precio_referencia(sin, {"precio_spy_usd": 0.0})["fuente_precio"] == "sin_dato"
    pago = {"estado_precio": "de_pago", "precio_usd": 19.99}
    assert b.precio_referencia(pago, {"precio_spy_usd": 5.0}) == {"precio_ref_usd": 19.99, "fuente_precio": "store"}


def test_extraer_spy():
    v, etiquetas = b.extraer_spy(SPY_GTA)
    assert v["resenas_total"] == 1990556 and v["aprobacion_pct"] == 87.41
    assert v["tiempo_mediano_horas"] == 93.82 and v["tiempo_promedio_horas"] == 261.58
    assert v["propietarios_bajo"] == 50_000_000 and round(v["propietarios_medio"]) == 70_710_678
    assert v["etiqueta_principal"] == "Open World" and len(etiquetas) == 3
    assert abs(sum(p for _, _, p in etiquetas) - 1) < 1e-9
    # un juego sin etiquetas ni resenas no rompe nada (SteamSpy devuelve [] sin etiquetas)
    vacio, sin = b.extraer_spy({"appid": 1, "positive": 0, "negative": 0, "owners": "0 .. 20,000", "tags": []})
    assert vacio["aprobacion_pct"] is None and vacio["n_etiquetas"] == 0 and sin == []


def test_construir_omite_lo_incompleto():
    with tempfile.TemporaryDirectory() as tmp:
        raw, out = Path(tmp) / "raw", Path(tmp) / "out"
        raw.mkdir()
        guardar(raw / "store" / "440.json", STORE_TF2)
        guardar(raw / "steamspy" / "440.json", dict(SPY_GTA, appid=440))
        guardar(raw / "store" / "999.json", {"success": False})
        guardar(raw / "store" / "997.json", STORE_TF2)          # sin ficha de SteamSpy
        with (raw / "muestra.csv").open("w", newline="", encoding="utf-8") as f:
            escritor = csv.writer(f)
            escritor.writerow(["appid", "nombre", "grupo", "posicion_propietarios"])
            for fila in [(440, "TF2", "top", 5), (999, "X", "aleatoria", 9), (998, "Y", "aleatoria", 10),
                         (997, "Z", "aleatoria", 11)]:
                escritor.writerow(fila)
        tabla, omitidos, total = b.construir(raw, out)
        assert total == 4 and len(tabla) == 1 and tabla.iloc[0]["appid"] == 440
        assert omitidos == {"sin_store": 1, "store_no_valido": 1, "sin_spy": 1}, omitidos
        assert (out / "steam_juegos.csv").exists() and (out / "steam_etiquetas.csv").exists()
        largo = list(csv.DictReader((out / "steam_generos.csv").open(encoding="utf-8")))
        assert largo == [{"appid": "440", "genero": "Action"}], largo


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for prueba in pruebas:
        prueba()
        print("OK ", prueba.__name__)
    print(f"\n{len(pruebas)} pruebas pasaron")
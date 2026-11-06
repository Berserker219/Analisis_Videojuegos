"""Funciones de limpieza para las respuestas de la Steam Store API y SteamSpy.

Formatos tomados de salidas reales (l=english, cc=us):
  Store    release_date    -> {'coming_soon': False, 'date': 'Dec 9, 2020'}
  Store    price_overview  -> {'currency': 'USD', 'initial': 5999, 'final': 5999, 'discount_percent': 0, ...}
  Store    supported_languages -> 'English<strong>*</strong>, French<strong>*</strong>, Arabic, ...'
  SteamSpy owners          -> '20,000,000 .. 50,000,000'
  SteamSpy price           -> '1799' (centavos de dolar)
  SteamSpy tags            -> {'Cyberpunk': 6625, 'Open World': 6081, ...}
"""

import re
from datetime import datetime

FORMATOS_FECHA = ("%b %d, %Y", "%d %b, %Y", "%B %d, %Y", "%b %Y", "%B %Y", "%Y")


def parse_release_date(rd):
    """Store release_date -> datetime, o None si no se puede (proximamente, TBA, formato raro)."""
    if not rd or rd.get("coming_soon"):
        return None
    texto = (rd.get("date") or "").strip()
    for fmt in FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, fmt)
        except ValueError:
            continue
    return None


def parse_price_store(po):
    """Store price_overview -> (precio_inicial, precio_final, descuento_pct) en dolares.

    Si el juego no trae price_overview (gratuito o no disponible), devuelve (None, None, None).
    Usa is_free de la Store para distinguir gratuito de no disponible.
    """
    if not po:
        return None, None, None
    return po["initial"] / 100, po["final"] / 100, po["discount_percent"]


def parse_price_spy(valor):
    """SteamSpy price / initialprice (centavos como texto o numero) -> dolares, o None."""
    try:
        return int(valor) / 100
    except (TypeError, ValueError):
        return None


def parse_owners(texto):
    """SteamSpy owners '20,000,000 .. 50,000,000' -> (bajo, alto, punto_medio).

    El punto medio es geometrico, porque los rangos crecen de forma multiplicativa.
    Si el limite bajo es 0 se usa la mitad del alto.
    """
    numeros = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", texto or "")]
    if len(numeros) != 2:
        return None, None, None
    bajo, alto = numeros
    medio = (bajo * alto) ** 0.5 if bajo > 0 else alto / 2
    return bajo, alto, medio


def parse_languages(texto):
    """Store supported_languages (con HTML) o SteamSpy languages (texto plano)
    -> (lista_de_idiomas, conjunto_con_audio_completo).

    Un asterisco entre <strong> marca idiomas con audio completo (segun recuerdo de la Store; confirmar).
    """
    if not texto:
        return [], set()
    cuerpo = re.split(r"<br\s*/?>", texto)[0]   # a veces trae una nota al pie despues de un salto de linea
    idiomas, audio = [], set()
    for item in cuerpo.split(","):
        limpio = re.sub(r"<[^>]+>", "", item).replace("*", "").strip()
        if not limpio:
            continue
        idiomas.append(limpio)
        if "<strong>*</strong>" in item:
            audio.add(limpio)
    return idiomas, audio


def tiene_espanol(idiomas):
    """True si ofrece cualquier variante de espanol."""
    return any(i.lower().startswith("spanish") for i in idiomas)


def tiene_espanol_latam(idiomas):
    """True si ofrece espanol de Latinoamerica."""
    return any("spanish" in i.lower() and "latin america" in i.lower() for i in idiomas)


def top_tags(tags, n=5):
    """SteamSpy tags {etiqueta: votos} -> [(etiqueta, proporcion_de_votos)].

    Se usa la proporcion y no los votos crudos: los votos crecen con la popularidad del juego.
    SteamSpy devuelve una lista vacia cuando no hay etiquetas.
    """
    if not isinstance(tags, dict) or not tags:
        return []
    total = sum(tags.values())
    ordenadas = sorted(tags.items(), key=lambda kv: -kv[1])[:n]
    return [(t, v / total) for t, v in ordenadas]


if __name__ == "__main__":
    # Pruebas con los valores reales de tu salida (Cyberpunk 2077, appid 1091500)
    print(parse_release_date({"coming_soon": False, "date": "Dec 9, 2020"}))
    print(parse_release_date({"coming_soon": True, "date": "Coming soon"}))
    print(parse_release_date({"coming_soon": False, "date": "Dec 2020"}))
    print(parse_price_store({"currency": "USD", "initial": 5999, "final": 5999, "discount_percent": 0}))
    print(parse_price_store(None))
    print(parse_price_spy("1799"), parse_price_spy("5999"))
    print(parse_owners("20,000,000 .. 50,000,000"))
    print(parse_owners("0 .. 20,000"))
    store = "English<strong>*</strong>, French<strong>*</strong>, Italian<strong>*</strong>, Spanish - Spain<strong>*</strong>, Arabic, Japanese<strong>*</strong>"
    print(parse_languages(store))
    spy = "English, French, Spanish - Spain, Spanish - Latin America, Thai"
    idiomas, _ = parse_languages(spy)
    print(tiene_espanol(idiomas), tiene_espanol_latam(idiomas))
    print(top_tags({"Cyberpunk": 6625, "Open World": 6081, "Nudity": 5287, "RPG": 5037, "Singleplayer": 4975}, 3))
    print(top_tags([]))
    print("reseñas / propietarios:", f"{904562 / 50_000_000:.1%} a {904562 / 20_000_000:.1%}")
"""Meteo della città scelta dall'utente (Open-Meteo: gratuito, senza registrazione)."""
import threading
import time
import urllib.parse

from .util import get_json, log

GEO = "https://geocoding-api.open-meteo.com/v1/search?count=6&language=it&format=json&name="
NOW = ("https://api.open-meteo.com/v1/forecast?current=temperature_2m,weather_code,is_day"
       "&timezone=auto&latitude={lat}&longitude={lon}")

# codice WMO -> (testo, icona di giorno, icona di notte)
WMO = {0: ("Sereno", "☀️", "🌙"), 1: ("Poco nuvoloso", "🌤️", "🌙"), 2: ("Parz. nuvoloso", "⛅", "☁️"),
       3: ("Nuvoloso", "☁️", "☁️"), 45: ("Nebbia", "🌫️", "🌫️"), 48: ("Nebbia", "🌫️", "🌫️"),
       51: ("Pioviggine", "🌦️", "🌧️"), 53: ("Pioviggine", "🌦️", "🌧️"), 55: ("Pioviggine", "🌧️", "🌧️"),
       61: ("Pioggia debole", "🌦️", "🌧️"), 63: ("Pioggia", "🌧️", "🌧️"), 65: ("Pioggia forte", "🌧️", "🌧️"),
       66: ("Pioggia gelata", "🌧️", "🌧️"), 67: ("Pioggia gelata", "🌧️", "🌧️"),
       71: ("Neve debole", "🌨️", "🌨️"), 73: ("Neve", "🌨️", "🌨️"), 75: ("Neve forte", "❄️", "❄️"),
       77: ("Nevischio", "🌨️", "🌨️"), 80: ("Rovesci", "🌦️", "🌧️"), 81: ("Rovesci", "🌧️", "🌧️"),
       82: ("Rovesci forti", "⛈️", "⛈️"), 85: ("Rovesci di neve", "🌨️", "🌨️"),
       86: ("Rovesci di neve", "❄️", "❄️"), 95: ("Temporale", "⛈️", "⛈️"),
       96: ("Temporale e grandine", "⛈️", "⛈️"), 99: ("Temporale e grandine", "⛈️", "⛈️")}


def describe(current):
    text, day, night = WMO.get(int(current.get("weather_code", -1)), ("", "🌡️", "🌡️"))
    return {"temp": round(current.get("temperature_2m", 0)), "text": text,
            "icon": day if current.get("is_day", 1) else night}


class Meteo:
    def __init__(self, prefs):
        self.prefs = prefs
        self.lock = threading.Lock()
        self.cache = (0.0, None)

    def search(self, name):
        name = (name or "").strip()
        if not name:
            return {"results": []}
        try:
            d = get_json(GEO + urllib.parse.quote(name))
        except Exception as ex:
            return {"error": f"Ricerca non riuscita ({ex})"}
        res = [{"name": r.get("name"),
                "area": ", ".join(x for x in (r.get("admin2") or r.get("admin1"), r.get("country")) if x),
                "lat": r.get("latitude"), "lon": r.get("longitude"), "it": r.get("country_code") == "IT"}
               for r in d.get("results", [])]
        res.sort(key=lambda r: not r["it"])          # prima le città italiane
        return {"results": res[:5]}

    def set_city(self, q):
        try:
            city = {"name": q["name"][:40], "lat": float(q["lat"]), "lon": float(q["lon"])}
        except (KeyError, ValueError):
            return {"ok": False}
        self.prefs.set("meteo", city)
        self.cache = (0.0, None)
        return {"ok": True, "city": city}

    def now(self):
        """Meteo attuale, aggiornato al massimo ogni 15 minuti."""
        city = self.prefs.get("meteo")
        if not city:
            return {"city": None}
        with self.lock:
            t, data = self.cache
            if data and data["city"] == city["name"] and time.monotonic() - t < 900:
                return data
            try:
                cur = get_json(NOW.format(lat=city["lat"], lon=city["lon"]))["current"]
                data = dict(describe(cur), city=city["name"])
            except Exception as ex:
                log.warning("meteo non disponibile: %s", ex)
                return data or {"city": city["name"], "error": True}
            self.cache = (time.monotonic(), data)
            return data

    def api(self, q):
        a = q.get("action", "now")
        if a == "search":
            return self.search(q.get("q"))
        if a == "set":
            return self.set_city(q)
        return self.now()

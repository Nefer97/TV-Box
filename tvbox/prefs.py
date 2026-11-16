"""Preferenze dell'utente (scelte fatte dalla TV), tutte in ~/.config/tvbox/prefs.json.

La V1 le teneva in quattro file (siti.json, home.json, meteo.json, screen.json): al primo
avvio vengono lette e riunite qui; i file vecchi restano dove sono (copia di sicurezza).

Contenuto:
    sites   [{"label", "url", "home": bool, "mobile": bool}]   I miei siti
    hidden  ["id", ...]                                         riquadri nascosti
    meteo   {"name", "lat", "lon"} | None                       città del meteo
    screen  {"mode": "auto" | "LxA", "video_low": bool}         risoluzione
    startup "last" | "home"                                     all'accensione: ultimo canale o home
    last_channel  "rai1" | None                                 canale in diretta lasciato acceso
    saver_off  minuti                                           schermo spento dopo tanto salvaschermo (0 = mai)
    ms_history [{"series","title","poster","episode","n","t"}]  Mediaset: Continua a guardare
    channels   ["rai1", ...]                                    canali in diretta scelti, in ordine
"""
import copy
import os
import threading

from .util import USER_DIR, log, read_json, write_json

DEFAULTS = {
    "version": 2,
    "sites": [],
    "hidden": [],
    "meteo": None,
    "screen": {"mode": "auto", "video_low": True},
    "startup": "last",
    "last_channel": None,
    "saver_off": 60,
    "ms_history": [],
    "channels": ["rai1", "rai2", "rai3", "rete4", "canale5", "italia1", "realtime", "dmax", "nove"],
}


class Prefs:
    def __init__(self, folder=USER_DIR):
        self.folder = folder
        self.path = os.path.join(folder, "prefs.json")
        self.lock = threading.RLock()
        self.data = self._load()

    # ---------- lettura / migrazione ----------
    def _load(self):
        d = read_json(self.path)
        if isinstance(d, dict):
            return self._clean(d)
        d = self._from_v1()
        try:
            write_json(self.path, d)
            log.info("preferenze: create in %s", self.path)
        except OSError as ex:
            log.warning("preferenze non salvate: %s", ex)
        return d

    def _from_v1(self):
        old = lambda name: read_json(os.path.join(self.folder, name))   # noqa: E731
        d = copy.deepcopy(DEFAULTS)
        sites = old("siti.json")
        if isinstance(sites, list):
            d["sites"] = sites
        home = old("home.json")
        if isinstance(home, dict):
            d["hidden"] = home.get("hidden", [])
        meteo = old("meteo.json")
        if isinstance(meteo, dict):
            d["meteo"] = meteo
        screen = old("screen.json")
        if isinstance(screen, dict):
            d["screen"].update({k: screen[k] for k in ("mode", "video_low") if k in screen})
        return self._clean(d)

    @staticmethod
    def _clean(d):
        """Tiene solo valori validi: un file rovinato non deve bloccare la TV."""
        out = copy.deepcopy(DEFAULTS)
        sites = d.get("sites")
        if isinstance(sites, list):
            out["sites"] = [
                {"label": str(x.get("label") or x["url"])[:40], "url": x["url"],
                 "home": bool(x.get("home")), "mobile": bool(x.get("mobile"))}
                for x in sites if isinstance(x, dict) and isinstance(x.get("url"), str)]
        hidden = d.get("hidden")
        if isinstance(hidden, list):
            out["hidden"] = [x for x in hidden if isinstance(x, str)]
        m = d.get("meteo")
        if isinstance(m, dict) and {"name", "lat", "lon"} <= m.keys():
            try:
                out["meteo"] = {"name": str(m["name"])[:40], "lat": float(m["lat"]), "lon": float(m["lon"])}
            except (TypeError, ValueError):
                pass
        s = d.get("screen")
        if isinstance(s, dict):
            mode = s.get("mode")
            if isinstance(mode, str) and (mode == "auto" or "x" in mode):
                out["screen"]["mode"] = mode
            out["screen"]["video_low"] = s.get("video_low", True) is not False
        if d.get("startup") in ("last", "home"):
            out["startup"] = d["startup"]
        if isinstance(d.get("last_channel"), str):
            out["last_channel"] = d["last_channel"]
        if isinstance(d.get("saver_off"), int) and 0 <= d["saver_off"] <= 24 * 60:
            out["saver_off"] = d["saver_off"]
        ch = d.get("channels")
        if isinstance(ch, list):
            out["channels"] = [x for x in ch if isinstance(x, str)][:60]
        h = d.get("ms_history")
        if isinstance(h, list):
            out["ms_history"] = [x for x in h if isinstance(x, dict) and isinstance(x.get("series"), str)
                                 and isinstance(x.get("episode"), str)][:12]
        return out

    # ---------- accesso ----------
    def get(self, key):
        with self.lock:
            return copy.deepcopy(self.data[key])

    def set(self, key, value):
        with self.lock:
            self.data[key] = copy.deepcopy(value)
            self.data = self._clean(self.data)
            write_json(self.path, self.data)
            return copy.deepcopy(self.data[key])

    def update(self, key, fn):
        """Modifica atomica: fn(valore attuale) -> valore nuovo."""
        with self.lock:
            return self.set(key, fn(self.get(key)))

"""Preferenze dell'utente (scelte fatte dalla TV), tutte in ~/.config/tvbox/prefs.json.

Contenuto:
    sites   [{"label", "url", "home": bool, "mobile": bool}]   I miei siti
    hidden  ["id", ...]                                         riquadri nascosti (non i canali)
    pinned  ["id", ...]                                         servizi di Altri servizi messi anche in home
    meteo   {"name", "lat", "lon"} | None                       città del meteo
    screen  {"mode": "auto" | "LxA", "video_low": bool}         risoluzione
    startup "last" | "home"                                     all'accensione: ultimo canale o home
    last_channel  "rai1" | None                                 canale in diretta lasciato acceso
    saver_off  minuti                                           schermo spento dopo tanto salvaschermo (0 = mai)
    ms_history [{"series","title","poster","episode","n","t"}]  Mediaset: Continua a guardare
    mio_history  come ms_history                               Il mio catalogo: Continua a guardare
    ms_user    "email"                                          account Mediaset collegato (solo da mostrare)
    progress   {"<url episodio>": [secondi, durata, quando]}    dove si è arrivati negli episodi (ultimi 200)
    channels   ["rai1", ...]                                    canali in diretta scelti, in ordine

Versioni del file: 2 = V2/V3; 3 = V4 (i canali non si nascondono più con "hidden": un canale
nascosto con la V3 esce dalla scelta dei canali).
"""
import copy
import os
import threading

from .channels import DEFAULT as DEFAULT_CHANNELS, IDS as CHANNEL_IDS
from .util import USER_DIR, log, read_json, write_json

VERSION = 3
PROGRESS_MAX = 200     # episodi di cui si ricorda dove si è arrivati

DEFAULTS = {
    "version": VERSION,
    "sites": [],
    "hidden": [],
    "pinned": [],
    "meteo": None,
    "screen": {"mode": "auto", "video_low": True},
    "startup": "last",
    "last_channel": None,
    "saver_off": 60,
    "ms_history": [],
    "progress": {},
    "mio_history": [],
    "ms_user": "",
    "channels": list(DEFAULT_CHANNELS),
}


class Prefs:
    def __init__(self, folder=USER_DIR):
        self.folder = folder
        self.path = os.path.join(folder, "prefs.json")
        self.lock = threading.RLock()
        self.data = self._load()

    # ---------- lettura ----------
    def _load(self):
        d = read_json(self.path)
        if not isinstance(d, dict):
            d = {}
        old = d.get("version")
        d = self._clean(self._upgrade(d))
        if old != VERSION:
            try:
                write_json(self.path, d)
                log.info("preferenze: %s (versione %s)", self.path, VERSION)
            except OSError as ex:
                log.warning("preferenze non salvate: %s", ex)
        return d

    @staticmethod
    def _upgrade(d):
        """Dalla versione 2: i canali nascosti escono dalla scelta e da "hidden"."""
        if d.get("version") == 2 and isinstance(d.get("hidden"), list):
            gone = {x for x in d["hidden"] if x in CHANNEL_IDS}
            if isinstance(d.get("channels"), list):
                d["channels"] = [x for x in d["channels"] if x not in gone]
            d["hidden"] = [x for x in d["hidden"] if x not in gone]
        return d

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
            out["hidden"] = [x for x in hidden if isinstance(x, str) and x not in CHANNEL_IDS]
        pinned = d.get("pinned")
        if isinstance(pinned, list):
            out["pinned"] = [x for x in pinned if isinstance(x, str) and x not in CHANNEL_IDS][:20]
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
            out["channels"] = [x for x in ch if isinstance(x, str)][:60] or list(DEFAULT_CHANNELS)
        pr = d.get("progress")
        if isinstance(pr, dict):
            ok = {u: [float(v[0]), float(v[1]), int(v[2])] for u, v in pr.items()
                  if isinstance(u, str) and isinstance(v, list) and len(v) == 3
                  and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v) and v[1] > 0}
            out["progress"] = dict(sorted(ok.items(), key=lambda kv: kv[1][2])[-PROGRESS_MAX:])
        if isinstance(d.get("ms_user"), str):
            out["ms_user"] = d["ms_user"][:80]
        for key in ("ms_history", "mio_history"):
            h = d.get(key)
            if isinstance(h, list):
                out[key] = [x for x in h if isinstance(x, dict) and isinstance(x.get("series"), str)
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

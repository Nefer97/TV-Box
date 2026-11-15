"""Lettura di config.json e normalizzazione dei servizi.

Ogni servizio ha un "kind" che decide come si comporta col telecomando:

    hbbtv   app per TV HbbTV (RaiPlay): Chrome si presenta come televisore, i tasti vanno
            all'app, "indietro" è il tasto TV 461
    tvapp   app "leanback" per TV (YouTube TV): i tasti vanno all'app, "indietro" è Esc
    web     sito normale: navigazione assistita, tasti del player (volume/salti),
            "indietro" = pagina precedente
    page    pagina del launcher (Altri servizi, Impostazioni, I miei siti)

Le identità (user agent) hanno un nome in "identities" e i servizi le citano con
"identity"; "block" elenca liste di indirizzi da bloccare ("ads", "trackers").
"""
import json
import os

from .util import BASE, log

CANDIDATES = [os.environ.get("TV_CONFIG", ""), "/etc/tvbox/config.json",
              os.path.join(BASE, "config.json")]

KIND_DEFAULTS = {
    "hbbtv": {"assist": False, "player_keys": False, "auto_fullscreen": False, "back": "tvkey"},
    "tvapp": {"assist": False, "player_keys": False, "auto_fullscreen": False, "back": "esc"},
    "web":   {"assist": True, "player_keys": True, "auto_fullscreen": False, "back": "history"},
    "page":  {"assist": False, "player_keys": False, "auto_fullscreen": False, "back": "history"},
}

# campi che il launcher riceve per disegnare i riquadri
UI_FIELDS = ("label", "subtitle", "icon", "color", "page", "onair", "live", "no_logo", "url", "logo_url")


def normalize_service(sid, raw, identities):
    """Dizionario completo e coerente per un servizio (campi mancanti -> valori del tipo)."""
    kind = raw.get("kind") or ("page" if raw.get("page") else "web")
    if kind not in KIND_DEFAULTS:
        log.warning("servizio %s: tipo %r sconosciuto, uso 'web'", sid, kind)
        kind = "web"
    s = dict(KIND_DEFAULTS[kind])
    s.update(raw)
    s["id"], s["kind"] = sid, kind
    s["label"] = raw.get("label") or sid
    ident = raw.get("identity")
    s["ua"] = identities.get(ident) if ident else None
    if ident and not s["ua"]:
        log.warning("servizio %s: identità %r non definita", sid, ident)
    s["live"] = bool(raw.get("live"))
    s["block"] = list(raw.get("block") or [])
    return s


class Config:
    def __init__(self, data, path=None):
        self.path = path
        self.raw = data
        ids = data.get("identities") or {}
        self.services = {sid: normalize_service(sid, s, ids)
                         for sid, s in (data.get("services") or {}).items()}
        home = data.get("home") or {}
        self.sections = home.get("sections") or []
        self.other = home.get("other") or []

    @classmethod
    def load(cls, candidates=None):
        for p in candidates or CANDIDATES:
            if p and os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                log.info("configurazione: %s", p)
                return cls(data, p)
        raise SystemExit("config.json non trovato")

    def opt(self, path, default=None):
        """Valore annidato: opt("remote.long_press_ms", 800)."""
        node = self.raw
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def live_channels(self, hidden=()):
        """Canali con palinsesto, nell'ordine della home (per il pannello sopra le dirette)."""
        out = []
        for sec in self.sections:
            for sid in sec.get("items", []):
                s = self.services.get(sid)
                if s and s.get("onair") and sid not in hidden and sid not in out:
                    out.append(sid)
        return out

    def ui(self):
        """Quello che serve al launcher per disegnare la home (stesso formato della V1)."""
        return {"sections": self.sections, "other_services": self.other,
                "services": {sid: {k: s[k] for k in UI_FIELDS if k in s}
                             for sid, s in self.services.items()}}

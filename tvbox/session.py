"""Cosa si sta guardando: una sola "visione" alla volta, con le sue regole.

Si apre una visione per ogni cosa che va a schermo fuori dalla home:

    channel   un canale in diretta del catalogo (Rai 1, Canale 5, Real Time…)
    episode   un episodio scelto nella sezione Mediaset
    service   un servizio della home o di Altri servizi (RaiPlay, YouTube, La7…)
    site      un indirizzo di "I miei siti"

Il tipo decide tutto il resto, qui e solo qui (le regole sono provate dai test):

                    sipario  banner  sorveglianza  riapertura  ultimo canale  avvio audio
    channel            sì      sì         sì           sì            sì        (web) sì
    episode            sì      -          sì           -             -         sì
    service / site     -       -          -            -             -         -

Il "servizio" della visione (session.service) dice invece come si comporta la pagina con il
telecomando e con Chrome: tipo (hbbtv, web…), identità, blocchi, vista telefono… (config).
"""
import time
from urllib.parse import urlparse

from .config import normalize_service
from .health import Watch

CHANNEL, EPISODE, SERVICE, SITE = "channel", "episode", "service", "site"


class Session:
    def __init__(self, what, service, title=None, return_to=None, now=None):
        self.what = what
        self.service = service                       # dizionario normalizzato (config)
        self.sid = service["id"] or None             # id nel catalogo / config (None: sito, episodio)
        self.url = service["url"]
        self.title = title or service["label"]       # per il sipario: "Apro <title>…"
        self.color = service.get("color")
        self.return_to = return_to                   # pagina del launcher per MENU (es. "ms:<serie>")
        self.opened_at = time.monotonic() if now is None else now
        self.watch = Watch(self.sid or what, self.opened_at) if self.guarded else None

    # ---------- come nasce ----------
    @classmethod
    def for_service(cls, s, now=None):
        return cls(CHANNEL if s.get("live") else SERVICE, s, now=now)

    @classmethod
    def episode(cls, url, series, label="", now=None):
        s = normalize_service("", {"kind": "web", "label": "Mediaset Infinity", "url": url,
                                   "block": ["trackers"], "color": "#0f766e"}, {})
        return cls(EPISODE, s, title=label or "l'episodio", return_to="ms:" + series if series else None, now=now)

    @classmethod
    def site(cls, url, mobile=False, now=None):
        s = normalize_service("", {"kind": "web", "label": urlparse(url).hostname or url, "url": url,
                                   "auto_fullscreen": True, "shield": True, "block": ["ads"],
                                   "mobile": bool(mobile)}, {})
        return cls(SITE, s, now=now)

    # ---------- le regole ----------
    @property
    def live(self):
        """Canale in diretta: tasti della diretta, pannello, palinsesto."""
        return self.what == CHANNEL

    @property
    def curtain(self):
        """Sipario ("Apro …") finché il video non parte."""
        return self.what in (CHANNEL, EPISODE)

    @property
    def banner(self):
        """Banner del programma quando il video è partito."""
        return self.what == CHANNEL

    @property
    def guarded(self):
        """Sorveglianza: un video che si ferma da solo viene segnalato."""
        return self.what in (CHANNEL, EPISODE)

    @property
    def reopen(self):
        """Un video fermo viene riaperto (solo le dirette: un episodio riprenderebbe da capo)."""
        return self.what == CHANNEL

    @property
    def remember(self):
        """All'accensione si riparte da qui."""
        return self.what == CHANNEL

    @property
    def kick(self):
        """Pagina web con un video da avviare con l'audio e mettere a tutto schermo."""
        return self.service["kind"] == "web" and self.what in (CHANNEL, EPISODE)

    @property
    def auto_fullscreen(self):
        return self.service["kind"] == "web" and (bool(self.service.get("auto_fullscreen")) or self.kick)

    def owns(self, url):
        """La pagina appartiene a questa visione? (stesso indirizzo di partenza o stesso sito)"""
        if not url:
            return False
        if url.startswith(self.url.rstrip("/")):
            return True
        return (urlparse(url).hostname or "") == (urlparse(self.url).hostname or "-")

    def __repr__(self):
        return f"<{self.what} {self.sid or self.url}>"

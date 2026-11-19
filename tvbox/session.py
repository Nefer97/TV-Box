"""Cosa si sta guardando: una sola "visione" alla volta, con le sue regole.

Si apre una visione per ogni cosa che va a schermo fuori dalla home:

    channel   un canale in diretta del catalogo (Rai 1, Canale 5, Real Time…)
    episode   un episodio scelto nella sezione Mediaset o in StreamingCommunity
    service   un servizio della home o di Altri servizi (RaiPlay, YouTube, La7…)
    site      un indirizzo di "I miei siti" (o la pagina di accesso di StreamingCommunity)

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
        self.login = False                           # pagina di accesso di StreamingCommunity
        self.resume_at = None                        # episodio: secondi da cui ripartire
        self.key = self.url                          # episodio: indirizzo sotto cui si salva il punto
        self.referrer = None                         # provenienza da dichiarare aprendo la pagina
        self.progress_saved = 0.0                    # episodio: ultimo salvataggio del punto

    # ---------- come nasce ----------
    @classmethod
    def for_service(cls, s, now=None):
        return cls(CHANNEL if s.get("live") else SERVICE, s, now=now)

    @classmethod
    def episode(cls, url, series, label="", now=None, site="Mediaset Infinity", back="ms", color="#0f766e",
                referrer=None, key=None):
        """Episodio di una sezione catalogo (Mediaset, StreamingCommunity, AnimeUnity): MENU torna a
        "<back>:<serie>". Per un player aperto da solo (AnimeUnity: il player di vixcloud invece della
        pagina dell'episodio): referrer = sito da cui si dichiara di arrivare, key = indirizzo
        dell'episodio sul sito, sotto cui si salva e si cerca il punto di ripresa."""
        s = normalize_service("", {"kind": "web", "label": site, "url": url,
                                   "block": ["trackers"], "color": color}, {})
        v = cls(EPISODE, s, title=label or "l'episodio", return_to=f"{back}:{series}" if series else None, now=now)
        v.key, v.referrer = key or v.url, referrer
        return v

    @classmethod
    def site(cls, url, mobile=False, now=None):
        s = normalize_service("", {"kind": "web", "label": urlparse(url).hostname or url, "url": url,
                                   "auto_fullscreen": True, "shield": True, "block": ["ads"],
                                   "mobile": bool(mobile)}, {})
        return cls(SITE, s, now=now)

    @classmethod
    def login_page(cls, url, label, back, now=None):
        """Pagina di accesso di un sito (StreamingCommunity): un sito normale, con la tastiera a
        schermo; MENU torna alla sezione "<back>" e tvd rilegge l'accesso (TV.home)."""
        s = normalize_service("", {"kind": "web", "label": label, "url": url,
                                   "shield": True, "block": ["ads"]}, {})
        v = cls(SITE, s, title=label, return_to=back, now=now)
        v.login = True
        return v

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

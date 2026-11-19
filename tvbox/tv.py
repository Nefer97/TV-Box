"""La TV: stato, azioni e sorveglianza di Chrome.

I tasti arrivano dal telecomando come eventi; dispatch() capisce lo stato (keys.detect_mode),
legge nella tabella quale azione fare (keys.action_for) e chiama il metodo con quel nome.
Tutte le azioni girano una alla volta nel thread "worker" (coda), come in V1.
"""
import json
import queue
import re
import subprocess
import threading
import time
from urllib.parse import urlparse

from . import keys
from .actions import Actions
from .browser import Browser, inject_scripts
from .cdp import CDP
from .config import normalize_service
from .display import Display
from .epg import EPG
from .health import HealthMixin, resume_point
from .layer import LayerMixin
from .discovery import Discovery
from .mediaset import Mediaset
from .sc import SC
from .au import AU
from .panel import PanelMixin
from .session import Session
from .sleep import SleepMixin
from .sites import Sites, normalize_url
from .util import log

MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/130.0.0.0 Mobile Safari/537.36")

BLOCKLISTS = {
    # pubblicità sui siti dell'utente (I miei siti)
    "ads": ["*doubleclick.net*", "*googlesyndication.com*", "*googleadservices.com*",
            "*adservice.google.*", "*taboola.com*", "*outbrain.com*", "*popads.net*",
            "*popcash.net*", "*propellerads*", "*adsterra*", "*exoclick.com*", "*juicyads*",
            "*amazon-adsystem.com*", "*adnxs.com*", "*pubmatic.com*", "*rubiconproject.com*",
            "*criteo.com*", "*criteo.net*", "*onclickads*", "*hilltopads*", "*a-ads.com*",
            "*popunder*", "*clickadu*", "*adcash*", "*trafficjunky*", "*mgid.com*"],
    # statistiche e pubblicità delle dirette Mediaset: senza, Canale 5 parte in ~10 s invece
    # di ~14 e salta lo spot iniziale (misurato)
    "trackers": ["*imrworldwide.com*", "*adform.net*", "*permutive.app*", "*permutive.com*",
                 "*googletagmanager.com*", "*google-analytics.com*", "*youbora*", "*npaw*",
                 "*aswpsdkeu.com*", "*doubleclick.net*", "*googlesyndication.com*",
                 "*imasdk.googleapis.com*", "*t.mediaset.it*", "*scorecardresearch*", "*chartbeat*",
                 "*facebook.net*", "*criteo*", "*teads*", "*smartclip*", "*adsrvr*"],
}

NO_SERVICE = normalize_service("", {}, {})      # pagina che non appartiene a nessun servizio


# stato della pagina per i tasti: [video grande, tutto schermo, focus in un player incorporato grande]
FRAME_JS = """[!!(window.__tv && __tv.isPlayer()), !!document.fullscreenElement, (() => {
  const f = document.activeElement;
  if (!f || f.tagName !== 'IFRAME') return false;
  const r = f.getBoundingClientRect();
  return r.width * r.height > 0.6 * innerWidth * innerHeight;
})()]"""

class TV(Actions, LayerMixin, PanelMixin, SleepMixin, HealthMixin):
    def __init__(self, cfg, prefs, vinput=None):
        self.cfg, self.prefs = cfg, prefs
        self.launcher_url = f"http://127.0.0.1:{cfg.opt('http_port', 8765)}/"
        self.services = cfg.services
        self.display = Display(prefs, cfg.opt("screen.video_mode", ""))
        self.display.on_change = self._refit_window
        self.display.on_trial_expired = lambda: self.post(self.display.revert)
        self.cdp = CDP(cfg.opt("chrome.cdp_port", 9222), inject_scripts(cfg.opt("chrome.force_h264", True)))
        self.browser = Browser(cfg, self.launcher_url, self.display.scale_factor)
        self.epg = EPG(self.services, enabled=self.channel_list)
        self.sites = Sites(prefs)
        self.mediaset = Mediaset(prefs, self.cdp)
        self.discovery = Discovery(prefs, self.cdp)
        self.sc = SC(prefs, self.cdp)
        self.au = AU(prefs, self.cdp)
        self.input = vinput
        self.remote = None                 # RemoteLogic (per /api/info)
        self.actions = queue.Queue()
        # stato
        self.session = None                # cosa si sta guardando (session.Session), None = home
        self.pointer = False
        self.panel = False
        self.volume_until = 0.0            # barra del volume aperta con PLAY fino a…
        self.mode = keys.LAUNCHER          # ultimo stato calcolato (riusato nelle ripetizioni)
        self.default_ua = None
        self.view_override = False
        self.flags_script = None           # impostazioni del servizio per gli script della pagina
        self.flags = {}
        self.blocked = []
        self.dark_default = False          # fondo di Chrome blu (solo durante i cambi canale)
        self._player_cache = (0.0, (False, False, False))   # (quando, (video grande, tutto schermo, player incorporato))
        self._player_since = 0.0
        self._noplayer_since = 0.0
        self._resumed = False              # ultimo canale già riaperto all'avvio
        self._reopens = []                 # riaperture recenti delle dirette ferme
        self.sleep_at = 0.0                # timer di spegnimento: istante (0 = spento)
        self.sleep_warned = False
        self.asleep = False                # schermo spento dal timer

    def channel_list(self):
        """I canali in diretta scelti dall'utente, in ordine."""
        return self.cfg.live_channels(self.prefs.get("channels"))

    @property
    def current(self):
        """Id del canale o servizio che si sta guardando (None: home, sito, episodio)."""
        return self.session.sid if self.session else None

    # ---------- coda delle azioni ----------
    def post(self, fn, *args):
        self.actions.put((fn, args))

    def worker(self):
        while True:
            fn, args = self.actions.get()
            try:
                fn(*args)
            except Exception as ex:
                log.warning("azione %s fallita: %s", getattr(fn, "__name__", fn), ex)

    # ---------- dal telecomando ----------
    def on_remote(self, event):
        self.post(self.dispatch, event)

    def dispatch(self, event):
        kind = event[0]
        if self.asleep:                                 # schermo spento: il primo tasto lo riaccende
            return self.wake()
        if self.sleep_warned:                           # "spegnimento tra 1 minuto": tasto = annulla
            self.sleep_set(0)
            self.toast("Timer di spegnimento annullato")
            return
        if kind == "pointer":
            return self.pointer_move(event[1], event[2])
        key = event[1] if kind == "arrow" else kind
        if kind != "arrow" or event[2] == 0:          # nelle ripetizioni lo stato non cambia
            self.mode = keys.detect_mode(self.context())
        action = keys.action_for(self.mode, key)
        if action:
            getattr(self, action)(key)

    def context(self):
        url = self.url()
        if url.startswith(self.launcher_url):
            return keys.Context(on_launcher=True, pointer=self.pointer)
        s = self.service_for(url)
        live = bool(self.session and self.session.live and s is self.session.service)
        player = bool(s.get("player_keys")) and self.is_player()
        return keys.Context(panel=self.panel_active(), pointer=self.pointer, kind=s["kind"],
                            live=live, player=player, assist=bool(s.get("assist")),
                            fullscreen=not player and self.is_fullscreen(),
                            frame_player=not player and self._page_state()[2],
                            volume=time.monotonic() < self.volume_until)

    # ---------- utilità ----------
    def url(self):
        try:
            return self.cdp.eval("location.href", timeout=3) or ""
        except Exception:
            return ""

    def on_launcher(self, url=None):
        return (url if url is not None else self.url()).startswith(self.launcher_url)

    def service_for(self, url):
        """Il servizio a cui appartiene la pagina (quello della visione, o uno con lo stesso sito)."""
        if self.session and self.session.owns(url):
            return self.session.service
        host = urlparse(url).hostname or ""
        for s in self.services.values():
            if s.get("url") and urlparse(s["url"]).hostname == host:
                return s
        return NO_SERVICE

    def _page_state(self):
        """(video grande, pagina a tutto schermo, focus in un player incorporato grande): una sola
        domanda a Chrome, ricordata 0,7 s. Il player incorporato è un iframe che copre più del
        60% della finestra e ha il focus (ci si è cliccato dentro)."""
        t, v = self._player_cache
        if time.monotonic() - t < 0.7:
            return v
        try:
            r = self.cdp.eval(FRAME_JS, timeout=2)
            v = tuple(bool(x) for x in r) if isinstance(r, list) and len(r) == 3 else (False, False, False)
        except Exception:
            v = (False, False, False)
        self._player_cache = (time.monotonic(), v)
        return v

    def is_player(self):
        return self._page_state()[0]

    def is_fullscreen(self):
        return self._page_state()[1]

    def volume(self, delta=0):
        ctl = self.cfg.opt("audio.mixer", "Master")
        if delta:
            subprocess.run(["amixer", "-q", "-M", "sset", ctl, f"{abs(delta)}%{'+' if delta > 0 else '-'}",
                            "unmute"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        out = subprocess.run(["amixer", "-M", "get", ctl], capture_output=True, text=True).stdout
        m = re.search(r"\[(\d+)%\]", out)
        return int(m.group(1)) if m else None

    def _step(self, key):
        return int(self.cfg.opt("audio.volume_step", 5)) * (1 if key == "up" else -1)

    # ---------- aprire e chiudere ----------
    def mobile_ua(self):
        """Identità da smartphone Android con la stessa versione di Chrome installata."""
        if self.default_ua and "X11; Linux x86_64" in self.default_ua:
            return self.default_ua.replace("X11; Linux x86_64", "Linux; Android 14; Pixel 8") \
                                  .replace(" Safari/", " Mobile Safari/")
        return MOBILE_UA

    def set_view(self, s):
        """Vista "telefono": il sito come su uno smartphone, ingrandito a tutto schermo."""
        if self.view_override:
            self.cdp.call("Emulation.clearDeviceMetricsOverride")
            self.view_override = False
        if not s.get("mobile"):
            return
        try:
            w = self.cdp.eval("innerWidth", timeout=3) or 1280
            h = self.cdp.eval("innerHeight", timeout=3) or 720
            dpr = self.cdp.eval("devicePixelRatio", timeout=3) or 1.0
        except Exception:
            w, h, dpr = 1280, 720, 1.0
        width = int(self.cfg.opt("mobile_width", 800))
        scale = w / width
        self.cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": int(round(h / scale)), "mobile": True,
            "deviceScaleFactor": dpr * scale, "scale": scale})
        self.view_override = True

    def set_flags(self, s):
        """Impostazioni del servizio per gli script delle pagine nuove (window.__tvFlags):
        shield = protezione da cookie, popup e pubblicità (shield.js); hover = il riquadro
        giallo simula il passaggio del mouse (nav.js)."""
        flags = {"shield": bool(s.get("shield")), "hover": s.get("hover", True) is not False}
        if flags == self.flags and self.flags_script:
            return
        if self.flags_script:
            self.cdp.call("Page.removeScriptToEvaluateOnNewDocument", {"identifier": self.flags_script})
            self.flags_script = None
        src = f"window.__tvFlags = {json.dumps(flags)};" + ("window.__tvShield = 1;" if flags["shield"] else "")
        self.flags_script = self.cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": src}).get("identifier")
        self.flags = flags

    def set_blocked(self, names):
        urls = [u for n in names for u in BLOCKLISTS.get(n, [])]
        if urls == self.blocked:
            return
        if urls:
            self.cdp.call("Network.enable")
            self.cdp.call("Network.setBlockedURLs", {"urls": urls})
        else:
            self.cdp.call("Network.setBlockedURLs", {"urls": []})
            self.cdp.call("Network.disable")
        self.blocked = urls
        log.info("indirizzi bloccati: %d", len(urls))

    def _prepare(self, s):
        ua = s.get("ua") or (self.mobile_ua() if s.get("mobile") else None) or self.default_ua
        self.cdp.call("Emulation.setUserAgentOverride", {"userAgent": ua or ""})   # "" = Chrome normale
        try:
            self.set_view(s)
            self.set_flags(s)
            self.set_blocked(s.get("block") or [])
        except Exception as ex:
            log.warning("vista/protezione: %s", ex)

    # ---------- aprire e chiudere una visione ----------
    def open(self, sid):
        """Apre un canale o un servizio (id del catalogo o di config.json)."""
        s = self.services.get(sid)
        if s and s.get("url"):
            self.start(Session.for_service(s))

    def open_url(self, url):
        """Apre un indirizzo scelto dall'utente (I miei siti)."""
        u = normalize_url(url)
        if u:
            self.start(Session.site(u, mobile=(self.sites.find(u) or {}).get("mobile")))

    def open_episode(self, url, series, label="", **kw):
        """Episodio scelto nella sezione Mediaset o in StreamingCommunity (MENU torna alla serie);
        se lo si era lasciato a metà, riparte da lì (health._progress_tick)."""
        sess = Session.episode(url, series, label, **kw)
        sess.resume_at = resume_point((self.prefs.get("progress") or {}).get(sess.key))
        self.start(sess)

    def open_login(self, sid="sc"):
        """Il sito vero a schermo per l'accesso, quando quello fatto da tvd non basta (es.
        Mediaset chiede il captcha): MENU torna alla sezione."""
        from .discovery import LOGIN_URL as DPLUS_LOGIN
        from .mediaset import SITE
        from .sc import LOGIN_URL
        url = SITE if sid == "mediaset" else DPLUS_LOGIN if sid == "discovery" else LOGIN_URL
        label = "Accesso a " + self.services.get(sid, {}).get("label", sid)
        back = "settings" if sid == "discovery" else sid     # discovery+ non ha una sezione in tvbox
        self.start(Session.login_page(url, label, back=back))

    def start(self, sess, panel=None):
        """Mette a schermo una visione. Le regole (sipario, banner, avvio, ultimo canale) sono
        della visione; panel = dati del pannello da tenere a schermo (cambio dal pannello)."""
        log.info("apro %s", sess)
        self.unbook_now()                                # il sipario della visione di prima no
        self.panel = self.pointer = False
        self.volume_until = 0.0
        self.session = sess
        self._prepare(sess.service)
        if sess.curtain or panel:                # la pagina nuova nasce con sipario e/o pannello
            self.book(curtain=sess.title if sess.curtain else None, panel=panel)
        else:
            self.clear_dark()
        self.cdp.call("Page.navigate", {"url": sess.url, **({"referrer": sess.referrer} if sess.referrer else {})})
        if sess.kick:
            threading.Thread(target=self._kick_live, args=(sess,), daemon=True).start()
        if sess.remember:
            self.prefs.set("last_channel", sess.sid)
        if sess.banner and not panel:
            threading.Thread(target=self._banner, args=(sess,), daemon=True).start()

    def _kick_live(self, sess):
        """Video delle dirette web e degli episodi: lo avvia con l'audio e lo mette a tutto
        schermo appena può."""
        deadline = time.monotonic() + 30
        time.sleep(3)
        while time.monotonic() < deadline and self.session is sess:
            try:
                if self.cdp.eval("!!(window.__tv && __tv.kick())", timeout=4, gesture=True):
                    return
            except Exception:
                pass
            time.sleep(1.5)

    def home(self, key=None, page=None):
        log.info("HOME")
        if self.session and self.session.login:       # si lascia la pagina di accesso: com'è andata?
            try:
                self.sc.after_login()
            except Exception as ex:
                log.warning("dopo l'accesso: %s", ex)
        self.panel = self.pointer = False
        self.volume_until = 0.0
        self.display.set_lowres(False)
        self.session = None
        self.prefs.set("last_channel", None)            # spento dalla home: si riparte dalla home
        self.clear_dark()
        self.unbook_now()
        self._prepare(NO_SERVICE)
        self.cdp.close_other_pages()
        self.cdp.call("Page.navigate", {"url": self.launcher_url + (f"#{page}" if page else "")})

    # ---------- all'accensione: ultimo canale ----------
    def _resume(self):
        self._resumed = True
        sid = self.prefs.get("last_channel")
        if self.prefs.get("startup") == "last" and sid in self.services:
            log.info("riparto dall'ultimo canale: %s", sid)
            self.post(self.open, sid)

    # ---------- schermo ----------
    def _refit_window(self):
        """Dopo un cambio di risoluzione la finestra di Chrome deve riempire il nuovo schermo."""
        try:
            wid = self.cdp.call("Browser.getWindowForTarget").get("windowId")
            for state in ("normal", "fullscreen"):
                self.cdp.call("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": state}})
        except Exception as ex:
            log.debug("adattamento finestra: %s", ex)

    def screen_keep(self):
        if self.display.keep() and \
                abs(self.browser.wanted_dsf() - self.browser.dsf) > 0.01:
            log.info("cambia l'ingrandimento: riavvio Chrome")
            self.browser.kill()                      # la sorveglianza lo fa ripartire

    def _video_res_tick(self, player):
        """Ogni 2 s: risoluzione da video dopo 4 s di video, di nuovo piena dopo 8 s senza."""
        d = self.display
        if not d.video_mode:
            return
        if not d.video_low():
            if d.lowres:
                d.set_lowres(False)
            return
        now = time.monotonic()
        if player:
            self._noplayer_since = 0.0
            self._player_since = self._player_since or now
            if not d.lowres and now - self._player_since >= 4:
                d.set_lowres(True)
        else:
            self._player_since = 0.0
            self._noplayer_since = self._noplayer_since or now
            if d.lowres and now - self._noplayer_since >= 8:
                d.set_lowres(False)

    def _auto_fullscreen_tick(self, url):
        if self.on_launcher(url):
            return
        if self.session:
            auto = self.session.auto_fullscreen
        else:
            s = self.service_for(url)
            auto = s["kind"] == "web" and bool(s.get("auto_fullscreen"))
        if not auto:
            return
        if self.cdp.eval("!!(window.__tv && __tv.autoCandidate())", timeout=3):
            log.info("schermo intero automatico")
            self.cdp.eval("window.__tv.maximize()", timeout=3, gesture=True)

    # ---------- sorveglianza ----------
    def watchdog(self):
        fails = 0
        while True:
            if not self.browser.alive():
                self.cdp.drop()
                self.blocked, self.flags_script, self.flags, self.view_override = [], None, {}, False
                self.dark_default = False
                log.warning("Chrome non attivo: riavvio")
                self.browser.start()
                fails = 0
                time.sleep(5)
                continue
            try:
                self.cdp.eval("1", timeout=8)
                fails = 0
                if self.default_ua is None:
                    # identità vera di Chrome (non quella "travestita" da TV)
                    ua = self.cdp.call("Browser.getVersion", timeout=3).get("userAgent", "")
                    if ua and "HbbTV" not in ua:
                        self.default_ua = ua.replace("HeadlessChrome", "Chrome")
                if not self._resumed and self.default_ua is not None:
                    self._resume()
                if self.cdp.crashed.is_set():
                    self.cdp.crashed.clear()
                    self.home()
                self._sleep_tick()
                url = self.url()
                self._auto_fullscreen_tick(url)
                self._saver_tick(url)
                self._health_tick(url)
                if self.display.video_mode:
                    self._video_res_tick(not self.on_launcher(url) and self.is_player())
                if self.flags.get("shield"):         # popup in nuove schede: chiusi
                    self.cdp.close_other_pages()
            except Exception as ex:
                if time.monotonic() - self.browser.started_at >= 60:
                    fails += 1
                    log.warning("Chrome non risponde (%d): %s", fails, ex)
                    if fails >= 4:
                        log.error("Chrome bloccato: lo termino")
                        self.cdp.drop()
                        self.browser.kill()
                        fails = 0
            time.sleep(2)

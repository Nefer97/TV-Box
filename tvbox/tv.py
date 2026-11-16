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
from .browser import Browser, inject_scripts, overlay_script, panel_script
from .cdp import CDP
from .config import normalize_service
from .display import Display
from .epg import EPG
from .actions import Actions
from .health import HealthMixin, Watch
from .panel import PanelMixin
from .sleep import SleepMixin
from .mediaset import Mediaset
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


class TV(Actions, PanelMixin, SleepMixin, HealthMixin):
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
        self.mediaset = Mediaset(prefs)
        self.input = vinput
        self.remote = None                 # RemoteLogic (per /api/info)
        self.actions = queue.Queue()
        # stato
        self.current = None                # id del servizio aperto
        self.opened_url = None
        self.pointer = False
        self.panel = False
        self.mode = keys.LAUNCHER          # ultimo stato calcolato (riusato nelle ripetizioni)
        self.default_ua = None
        self.view_override = False
        self.shield_script = None
        self.blocked = []
        self.dark_default = False          # fondo di Chrome blu (solo durante i cambi canale)
        self._player_cache = (0.0, False)
        self._player_since = 0.0
        self._noplayer_since = 0.0
        self._resumed = False              # ultimo canale già riaperto all'avvio
        self._health = None                # sorveglianza della diretta aperta (health.Watch)
        self._reopens = []
        self._switching = False            # cambio canale dal pannello in corso (niente banner)
        self.sleep_at = 0.0                # timer di spegnimento: istante (0 = spento)
        self.sleep_warned = False
        self.asleep = False                # schermo spento dal timer

    def channel_list(self):
        """I canali in diretta scelti dall'utente, in ordine."""
        return self.cfg.live_channels(self.prefs.get("channels"), self.prefs.get("hidden"))

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
        live = bool(s.get("live")) and s.get("id") == self.current
        player = bool(s.get("player_keys")) and self.is_player()
        return keys.Context(panel=self.panel_active(), pointer=self.pointer, kind=s["kind"],
                            live=live, player=player, assist=bool(s.get("assist")))

    # ---------- utilità ----------
    def url(self):
        try:
            return self.cdp.eval("location.href", timeout=3) or ""
        except Exception:
            return ""

    def on_launcher(self, url=None):
        return (url if url is not None else self.url()).startswith(self.launcher_url)

    def service_for(self, url):
        """Il servizio a cui appartiene la pagina (quello aperto, o uno con lo stesso sito)."""
        cur = self.services.get(self.current or "")
        if cur and self.opened_url and url.startswith(self.opened_url.rstrip("/")):
            return cur
        host = urlparse(url).hostname or ""
        if cur and cur.get("url") and urlparse(cur["url"]).hostname == host:
            return cur
        for s in self.services.values():
            if s.get("url") and urlparse(s["url"]).hostname == host:
                return s
        return NO_SERVICE

    def is_player(self):
        t, v = self._player_cache
        if time.monotonic() - t < 0.7:
            return v
        try:
            v = bool(self.cdp.eval("!!(window.__tv && __tv.isPlayer())", timeout=2))
        except Exception:
            v = False
        self._player_cache = (time.monotonic(), v)
        return v

    def toast(self, msg):
        try:
            self.cdp.js("__tv.toast", msg, timeout=2)
        except Exception:
            pass

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

    def set_shield(self, on):
        """shield.js (cookie, popup, riquadri pubblicitari) acceso solo dove serve."""
        if on and not self.shield_script:
            r = self.cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": "window.__tvShield = 1;"})
            self.shield_script = r.get("identifier")
        elif not on and self.shield_script:
            self.cdp.call("Page.removeScriptToEvaluateOnNewDocument", {"identifier": self.shield_script})
            self.shield_script = None

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
            self.set_shield(bool(s.get("shield")))
            self.set_blocked(s.get("block") or [])
        except Exception as ex:
            log.warning("vista/protezione: %s", ex)

    def _clear_dark(self):
        if self.dark_default:
            try:
                self.cdp.call("Emulation.setDefaultBackgroundColorOverride", {})
            except Exception:
                pass
            self.dark_default = False

    def open(self, sid, keep_dark=False):
        s = self.services.get(sid)
        if not s or not s.get("url"):
            return
        if not keep_dark:
            self._clear_dark()
        log.info("apro %s", sid)
        self.panel = self.pointer = False
        self._prepare(s)
        pending = None
        if (s["live"] or s.get("curtain")) and not self._switching:   # diretta o episodio: il sipario
            label = s.get("curtain_label") or s["label"]
            pending = self._book({"channels": [{"id": sid, "label": label, "color": s.get("color")}],
                                  "current": sid, "curtain": True, "curtainOnly": True})
        self.current, self.opened_url = sid, s["url"]
        self._health = Watch(sid, time.monotonic())
        self.cdp.call("Page.navigate", {"url": s["url"]})
        if pending:
            threading.Thread(target=self._panel_unbook, args=(sid, pending), daemon=True).start()
        if s["live"] and s["kind"] == "web":
            threading.Thread(target=self._kick_live, daemon=True).start()
        if s["live"]:                         # canale in diretta: riparte da qui all'accensione
            self.prefs.set("last_channel", sid)
            if not self._switching:
                threading.Thread(target=self._banner, args=(sid,), daemon=True).start()

    def open_url(self, url):
        """Apre un indirizzo scelto dall'utente (I miei siti)."""
        u = normalize_url(url)
        if not u:
            return
        saved = self.sites.find(u) or {}
        self.services["__sito"] = normalize_service("__sito", {
            "kind": "web", "label": urlparse(u).hostname, "url": u, "auto_fullscreen": True,
            "shield": True, "block": ["ads"], "mobile": bool(saved.get("mobile"))}, {})
        self.open("__sito")

    def open_episode(self, url, series, label=""):
        """Episodio Mediaset scelto nella sezione Mediaset: la pagina del video del sito, a tutto
        schermo, senza tracciamenti, con il sipario finché non parte; MENU torna alla serie."""
        self.services["__episodio"] = normalize_service("__episodio", {
            "kind": "web", "label": "Mediaset Infinity", "url": url, "auto_fullscreen": True,
            "block": ["trackers"], "return_to": "ms:" + series, "curtain": True,
            "curtain_label": label or "l'episodio", "color": "#0f766e"}, {})
        self.open("__episodio")
        threading.Thread(target=self._kick_live, daemon=True).start()   # avvio con l'audio

    def _kick_live(self):
        """Dirette web: avvia il video con l'audio e lo mette a tutto schermo appena può."""
        deadline = time.monotonic() + 30
        time.sleep(3)
        while time.monotonic() < deadline:
            try:
                if self.cdp.eval("!!(window.__tv && __tv.kick())", timeout=4, gesture=True):
                    return
            except Exception:
                pass
            time.sleep(1.5)

    def home(self, key=None, page=None):
        log.info("HOME")
        self.panel = self.pointer = False
        self.display.set_lowres(False)
        self.current = self.opened_url = None
        self.prefs.set("last_channel", None)            # spento dalla home: si riparte dalla home
        self._clear_dark()
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
        s = self.services.get(self.current or "") or self.service_for(url)
        if s["kind"] != "web" or not (s.get("auto_fullscreen") or s["live"]):
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
                self.blocked, self.shield_script, self.view_override = [], None, False
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
                if self.shield_script:               # popup in nuove schede: chiusi
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

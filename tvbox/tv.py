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
from .browser import Browser, inject_scripts, panel_script
from .cdp import CDP
from .config import normalize_service
from .display import Display
from .epg import EPG
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

NO_SERVICE = normalize_service("", {}, {})

# script "prenotato" nella pagina del canale nuovo: appena esiste l'elemento radice (nel primo
# istante della pagina non c'è ancora: lo si aspetta con un MutationObserver) lo colora di blu
# e ci aggancia pannello e sipario, senza aspettare il corpo della pagina (che su Mediaset
# arriva tardi, dopo script pesanti). Va eseguito solo nella pagina principale.
BOOT_START = """(function () {
  var start = function () {
    var e = document.documentElement;
    if (!e) return false;
    e.style.setProperty('background', '#0b1020', 'important');
    try { window.__tvp.open(d); } catch (x) { console.error('[pannello]', x); }
    return true;
  };
  if (!start()) { var mo = new MutationObserver(function () { if (start()) mo.disconnect(); });
                  mo.observe(document, { childList: true }); }
})();"""
DARK = {"r": 11, "g": 16, "b": 32, "a": 1}      # pagina che non appartiene a nessun servizio


class TV:
    def __init__(self, cfg, prefs, vinput=None):
        self.cfg, self.prefs = cfg, prefs
        self.launcher_url = f"http://127.0.0.1:{cfg.opt('http_port', 8765)}/"
        self.services = cfg.services
        self.display = Display(prefs, cfg.opt("screen.video_mode", ""))
        self.display.on_change = self._refit_window
        self.display.on_trial_expired = lambda: self.post(self.display.revert)
        self.cdp = CDP(cfg.opt("chrome.cdp_port", 9222), inject_scripts(cfg.opt("chrome.force_h264", True)))
        self.browser = Browser(cfg, self.launcher_url, self.display.scale_factor)
        self.epg = EPG(self.services)
        self.sites = Sites(prefs)
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
        live = bool(s.get("onair")) and s.get("id") == self.current
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

    # ---------- azioni: tasti veri ----------
    def key_arrow(self, key):
        self.input.key(key)

    def key_enter(self, key=None):
        self.input.key("enter")

    def key_esc(self, key=None):
        self.input.key("esc")

    def _tv_key(self, code):
        """Tasto con codice da televisore, inviato tramite Chrome (461 indietro, 463 play)."""
        for t in ("rawKeyDown", "keyUp"):
            self.cdp.call("Input.dispatchKeyEvent", {"type": t, "windowsVirtualKeyCode": code,
                                                     "nativeVirtualKeyCode": code})

    def tv_back(self, key=None):
        self._tv_key(461)

    def tv_play(self, key=None):
        self._tv_key(463)

    # ---------- azioni: puntatore ----------
    def pointer_toggle(self, key=None):
        self.pointer = not self.pointer
        self.toast("Puntatore attivo: frecce per muovere, OK per cliccare"
                   if self.pointer else "Puntatore disattivato")
        if self.pointer:
            self.input.move(1, 1)                   # piccolo movimento per mostrarlo

    def pointer_off(self, key=None):
        self.pointer = False
        self.toast("Puntatore disattivato")

    def pointer_nudge(self, key):
        px = int(self.cfg.opt("remote.pointer_nudge_px", 12))
        self.pointer_move(key, px)

    def pointer_move(self, d, px):
        self.input.move({"left": -px, "right": px}.get(d, 0), {"up": -px, "down": px}.get(d, 0))

    def click(self, key=None):
        self.input.click()

    def click_at(self, x, y):
        """Clic "vero" nel punto x,y della pagina, tramite Chrome."""
        base = {"x": x, "y": y, "button": "left", "clickCount": 1}
        self.cdp.call("Input.dispatchMouseEvent", dict(base, type="mouseMoved", button="none"))
        self.cdp.call("Input.dispatchMouseEvent", dict(base, type="mousePressed"))
        self.cdp.call("Input.dispatchMouseEvent", dict(base, type="mouseReleased"))

    # ---------- azioni: video ----------
    def player_toggle(self, key=None):
        if not self.cdp.eval("!!(window.__tv && __tv.toggle())", timeout=3, gesture=True):
            self.input.key("space")

    def player_volume(self, key):
        v = self.volume(self._step(key))
        if v is not None:
            self.toast(f"🔊  Volume {v}%")

    def player_seek(self, key):
        sec = -int(self.cfg.opt("player.seek_back_s", 10)) if key == "left" \
            else int(self.cfg.opt("player.seek_forward_s", 30))
        self.cdp.js("__tv.seek", sec, timeout=3)

    # ---------- azioni: navigazione assistita ----------
    def nav_move(self, key):
        if not self.cdp.js("__nav.move", key, timeout=4):
            self.input.key(key)

    def nav_ok(self, key=None):
        r = self.cdp.eval("window.__nav ? __nav.activate() : null", timeout=4, gesture=True)
        if isinstance(r, dict) and "x" in r:
            self.click_at(r["x"], r["y"])
        elif not r:
            self.input.key("enter")

    def page_back(self, key=None):
        if self.cdp.eval("!!(window.__nav && __nav.back())", timeout=3):
            return                                   # chiusa la tastiera a schermo
        if self.cdp.eval("!!(window.__tv && __tv.exitFull())", timeout=3):
            return
        if self.cdp.eval("history.length > 1", timeout=3):
            self.cdp.eval("history.back()", timeout=3)
        else:
            self.home()

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
        self.current, self.opened_url = sid, s["url"]
        self.cdp.call("Page.navigate", {"url": s["url"]})
        if s["live"] and s["kind"] == "web":
            threading.Thread(target=self._kick_live, daemon=True).start()

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
        self._clear_dark()
        self._prepare(NO_SERVICE)
        self.cdp.close_other_pages()
        self.cdp.call("Page.navigate", {"url": self.launcher_url + (f"#{page}" if page else "")})

    # ---------- pannello cambio canale ----------
    def panel_active(self):
        if not self.panel:
            return False
        try:
            self.panel = bool(self.cdp.eval("!!(window.__tvp && __tvp.isOpen())", timeout=3))
        except Exception:
            self.panel = False
        return self.panel

    def panel_data(self):
        od = {}
        try:
            od = self.epg.onair()
        except Exception as ex:
            log.warning("palinsesti: %s", ex)
        chans = []
        for sid in self.cfg.live_channels(self.prefs.get("hidden")):
            s, o = self.services[sid], od.get(self.services[sid]["onair"]) or {}
            chans.append({"id": sid, "label": s["label"], "color": s.get("color"),
                          "title": o.get("title", ""), "start": o.get("start", 0), "end": o.get("end", 0),
                          "image": o.get("image", ""), "desc": (o.get("desc") or "")[:300]})
        return {"channels": chans, "current": self.current, "vol": self.volume(0),
                "videoLow": self.display.video_low() if self.display.video_mode else None}

    def panel_open(self, key=None):
        js = panel_script()
        data = json.dumps(self.panel_data())
        self.panel = bool(self.cdp.eval(f"{js}\n;window.__tvp.open({data})", timeout=6))
        log.info("pannello: %s", "aperto" if self.panel else "non riuscito")

    def panel_close(self, key=None):
        self.panel = False
        try:
            self.cdp.js("__tvp.close", timeout=3)
        except Exception:
            pass

    def panel_move(self, key):
        self.cdp.js("__tvp.move", key, timeout=3)

    def panel_volume(self, key):
        self.cdp.js("__tvp.set", "vol", self.volume(self._step(key)), timeout=3)

    def panel_ok(self, key=None):
        r = self.cdp.eval("window.__tvp ? __tvp.ok() : null", timeout=3)
        if not isinstance(r, dict):
            return
        a = r.get("act")
        if a == "open":
            sid = r.get("id")
            if sid == self.current:
                return self.panel_close()
            self.panel_switch(sid)
        elif a == "video":
            on = bool(r.get("on"))
            self.display.set_video_low(on)
            self.cdp.js("__tvp.set", "videoLow", on, timeout=3)
        elif a == "settings":
            self.home(page="settings")
        elif a == "home":
            self.home()

    def panel_switch(self, sid):
        """Cambio canale dal pannello senza che il pannello sparisca: prima di aprire il canale
        nuovo si "prenota" il pannello nella pagina che sta per nascere (script registrato per i
        documenti nuovi). Chrome tiene a schermo la pagina vecchia finché la nuova non disegna,
        e la nuova disegna subito il pannello: il passaggio è quasi senza stacco."""
        self.cdp.js("__tvp.set", "busy", sid, timeout=3)
        js = panel_script()
        data = self.panel_data()
        data["current"] = sid
        data["curtain"] = True              # fondo scuro finché il video nuovo non parte
        # la pagina nuova nasce già blu (prima di qualsiasi contenuto: niente lampo bianco),
        # poi il pannello con il sipario appena c'è il corpo della pagina
        # solo nella pagina principale (non nei riquadri interni di pubblicità e statistiche)
        boot = ("if (window.top === window) {\n" + js +
                f"\n;var d = {json.dumps(data)};\n" + BOOT_START + "\n}")
        pending = None
        try:
            pending = self.cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": boot}).get("identifier")
        except Exception as ex:
            log.warning("pannello prenotato: %s", ex)
        try:                                 # fondo di Chrome blu invece che bianco
            self.cdp.call("Emulation.setDefaultBackgroundColorOverride", {"color": DARK})
            self.dark_default = True
        except Exception:
            pass
        self.open(sid, keep_dark=True)
        self.panel = True
        threading.Thread(target=self._panel_unbook, args=(sid, pending), daemon=True).start()

    def _panel_unbook(self, sid, pending):
        """Appena il pannello c'è nella pagina nuova (o dopo 15 s) si toglie la prenotazione,
        così un ricaricamento successivo della pagina non lo fa ricomparire."""
        deadline = time.monotonic() + 15
        time.sleep(1)
        while time.monotonic() < deadline and self.current == sid:
            try:
                if self.cdp.eval("!!(window.__tvp && __tvp.isOpen())", timeout=3):
                    break
            except Exception:
                pass
            time.sleep(0.4)
        if pending:
            try:
                self.cdp.call("Page.removeScriptToEvaluateOnNewDocument", {"identifier": pending})
            except Exception:
                pass

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
                if self.cdp.crashed.is_set():
                    self.cdp.crashed.clear()
                    self.home()
                url = self.url()
                self._auto_fullscreen_tick(url)
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

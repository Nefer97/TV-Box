#!/usr/bin/env python3
"""
tvd — demone "Smart TV" per Mac mini + Apple Remote.

Un solo processo che:
  * avvia e sorveglia Google Chrome in modalità kiosk (riavvio automatico
    se si chiude, si blocca o il renderer va in crash);
  * serve il launcher (schermata principale) e una piccola API su 127.0.0.1;
  * legge l'Apple Remote (driver kernel hid-appleir) via evdev, lo "afferra"
    in esclusiva e traduce i tasti in frecce/Invio/Esc o in azioni
    (Home, Indietro, Play/Pausa, volume, modalità puntatore) tramite uinput
    e il Chrome DevTools Protocol (CDP).

Mappa tasti (telecomando bianco a 6 tasti):
    +  / −           -> Su / Giù            (in riproduzione: volume)
    |◀◀ / ▶▶|        -> Sinistra / Destra   (in riproduzione: −10 s / +30 s)
    centrale (▶❚❚)   -> OK                  (in riproduzione: pausa/riprendi)
    centrale tenuto  -> modalità puntatore (mouse) on/off
    MENU             -> Indietro
    MENU tenuto      -> Home (schermata principale)
Il telecomando in alluminio (7 tasti) è riconosciuto in automatico:
il tasto centrale è OK e ▶❚❚ è sempre Play/Pausa.
"""
import calendar
import hashlib
import json
import logging
import os
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import evdev
import websocket
from evdev import UInput
from evdev import ecodes as E

BASE = os.path.dirname(os.path.abspath(__file__))
LAUNCHER_DIR = os.path.join(BASE, "launcher")
CONFIG_CANDIDATES = [os.environ.get("TV_CONFIG", ""), "/etc/tvbox/config.json",
                     os.path.join(BASE, "config.json")]

log = logging.getLogger("tvd")


# --------------------------------------------------------------------------
# Risoluzione dello schermo: piena nei menu, più bassa durante i video (il Mac mini
# disegna tutto senza scheda grafica: a 1280x720 deve disegnare meno della metà dei punti)
# --------------------------------------------------------------------------
def xr_query():
    """(uscita, (larghezza, altezza) attuali, modo preferito "LxA", modi disponibili)"""
    out = subprocess.run(["xrandr", "--query"], capture_output=True, text=True, timeout=5).stdout
    cur = re.search(r"current (\d+) x (\d+)", out)
    output, pref, modes, inside = None, None, [], False
    for line in out.splitlines():
        if not line.startswith(" "):
            inside = " connected" in line
            if inside and output is None:
                output = line.split()[0]
            continue
        if inside and output:
            m = re.match(r"\s+(\d+x\d+)\S*\s+(.*)", line)
            if m:
                modes.append(m.group(1))
                if "+" in m.group(2) and pref is None:
                    pref = m.group(1)
    if pref is None and modes:
        pref = modes[0]
    return output, (int(cur.group(1)), int(cur.group(2))) if cur else None, pref, modes


def xr_set(mode):
    """Imposta la risoluzione ("auto" = quella preferita dallo schermo)."""
    output, _, _, modes = xr_query()
    if not output:
        return False
    args = ["--auto"] if mode == "auto" else ["--mode", mode]
    if mode != "auto" and mode not in modes:
        log.warning("risoluzione %s non disponibile su %s", mode, output)
        return False
    r = subprocess.run(["xrandr", "--output", output] + args, capture_output=True, text=True, timeout=10)
    log.info("schermo -> %s (%s)", mode, r.returncode)
    return r.returncode == 0


SCREEN_PATH = os.path.expanduser("~/.config/tvbox/screen.json")


def screen_prefs():
    try:
        with open(SCREEN_PATH, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def screen_saved():
    """Risoluzione scelta in Impostazioni ("auto" = quella preferita dallo schermo)."""
    return screen_prefs().get("mode") or "auto"


def screen_video_low():
    """Abbassare la risoluzione durante i video? (Impostazioni; di serie sì)"""
    return screen_prefs().get("video_low", True) is not False


def screen_save(mode=None, video_low=None):
    d = screen_prefs()
    if mode is not None:
        d["mode"] = mode
    if video_low is not None:
        d["video_low"] = bool(video_low)
    os.makedirs(os.path.dirname(SCREEN_PATH), exist_ok=True)
    with open(SCREEN_PATH + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(SCREEN_PATH + ".tmp", SCREEN_PATH)


def full_mode():
    """La risoluzione "normale" (fuori dai video): quella scelta, se lo schermo collegato la
    offre; altrimenti "auto". Così, cambiando TV, non si resta mai su un modo impossibile."""
    m = screen_saved()
    if m != "auto":
        try:
            if m in xr_query()[3]:
                return m
        except Exception:
            pass
    return "auto"


def auto_scale_factor():
    """Ingrandimento di Chrome in base all'altezza dello schermo: il launcher è pensato
    per 720 righe, quindi 1080 -> 1.5. Sotto le 900 righe (720, 768) resta 1.0: un
    ingrandimento non intero (es. 1.07) fa ricampionare tutto a Chrome e l'immagine
    diventa sfocata. Il launcher è comunque in proporzione allo schermo (vh)."""
    try:
        _, cur, pref, _ = xr_query()
        m = full_mode()
        m = pref if m == "auto" else m
        w, h = (int(x) for x in m.split("x")) if m else (cur or (1280, 720))
        dsf = 1.0 if h < 900 else round(h / 720, 2)
        log.info("schermo %sx%s: device_scale_factor %.2f", w, h, dsf)
        return dsf
    except Exception as ex:
        log.warning("xrandr non disponibile: %s", ex)
    return 1.0


def load_config():
    for p in CONFIG_CANDIDATES:
        if p and os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
            log.info("configurazione: %s", p)
            return cfg
    raise SystemExit("config.json non trovato")


# --------------------------------------------------------------------------
# JavaScript iniettato in ogni pagina (prima degli script del sito)
# --------------------------------------------------------------------------
HELPER_JS = r"""
(() => {
  if (window.__tv) return;
  const T = {};
  T.main = () => {
    let best = null, ba = 0;
    for (const v of document.querySelectorAll('video')) {
      const r = v.getBoundingClientRect(), a = r.width * r.height;
      if (a > ba) { ba = a; best = v; }
    }
    return best;
  };
  T.area = v => { const r = v.getBoundingClientRect();
                  return (r.width * r.height) / Math.max(1, innerWidth * innerHeight); };
  T.isPlayer = () => {
    const fs = document.fullscreenElement;
    if (fs) return !!(fs.tagName === 'VIDEO' || fs.querySelector('video'));
    if (document.documentElement.classList.contains('__tvmaxed')) return true;
    const v = T.main();
    return !!(v && v.readyState >= 2 && T.area(v) > 0.6);
  };
  T.toast = (msg) => {
    try {
      let d = document.getElementById('__tvtoast');
      if (!d) {
        d = document.createElement('div'); d.id = '__tvtoast';
        d.style.cssText = 'position:fixed;left:50%;bottom:8vh;transform:translateX(-50%);' +
          'z-index:2147483647;background:rgba(0,0,0,.82);color:#fff;font:600 34px/1.2 sans-serif;' +
          'padding:18px 36px;border-radius:18px;pointer-events:none;transition:opacity .3s';
        (document.fullscreenElement && document.fullscreenElement.tagName !== 'VIDEO'
          ? document.fullscreenElement : document.documentElement).appendChild(d);
      }
      d.textContent = msg; d.style.opacity = '1';
      clearTimeout(T._tt); T._tt = setTimeout(() => d.style.opacity = '0', 1600);
    } catch (e) {}
  };
  T.toggle = () => {
    const v = T.main(); if (!v) return false;
    if (v.paused) { v.play().catch(() => {}); T.toast('▶  Riproduci'); }
    else { v.pause(); T.toast('❚❚  Pausa'); }
    return true;
  };
  T.seek = (d) => {
    const v = T.main(); if (!v) return false;
    let t = v.currentTime + d; const s = v.seekable;
    if (s && s.length) t = Math.max(s.start(0), Math.min(s.end(s.length - 1) - 1, t));
    try { v.currentTime = t; } catch (e) {}
    T.toast((d > 0 ? '▶▶  +' : '◀◀  −') + Math.abs(d) + ' s'); return true;
  };
  T.cssMax = (v) => {
    if (!document.getElementById('__tvmaxstyle')) {
      const st = document.createElement('style'); st.id = '__tvmaxstyle';
      st.textContent = '.__tvmax{position:fixed!important;inset:0!important;width:100vw!important;' +
        'height:100vh!important;max-width:none!important;max-height:none!important;' +
        'z-index:2147483646!important;background:#000!important;object-fit:contain!important;}' +
        'html.__tvmaxed,html.__tvmaxed body{overflow:hidden!important;background:#000!important}';
      document.head.appendChild(st);
    }
    v.classList.add('__tvmax'); document.documentElement.classList.add('__tvmaxed');
  };
  // lo schermo intero è già sul video giusto? (dopo la pubblicità il sito cambia video)
  T.fsOk = (v) => { const fs = document.fullscreenElement; return !!fs && (fs === v || fs.contains(v)); };
  T.maximize = () => {
    const v = T.main(); if (!v) return false;
    if (T.fsOk(v)) return true;
    const go = () => {
      try {
        const p = v.requestFullscreen();
        if (p && p.catch) p.catch(() => T.cssMax(v));
      } catch (e) { T.cssMax(v); }
    };
    if (document.fullscreenElement) document.exitFullscreen().then(go, go);   // era sulla pubblicità
    else go();
    return true;
  };
  T.exitFull = () => {
    const v = T.main();
    if (document.fullscreenElement) {
      if (v) v.dataset.tvNoAuto = '1';
      document.exitFullscreen().catch(() => {}); return true;
    }
    if (document.documentElement.classList.contains('__tvmaxed')) {
      if (v) { v.dataset.tvNoAuto = '1'; v.classList.remove('__tvmax'); }
      document.documentElement.classList.remove('__tvmaxed'); return true;
    }
    return false;
  };
  // Video "vero" che sta suonando: non muto (esclude anteprime), lungo o in diretta.
  T.autoCandidate = () => {
    const v = T.main();
    if (!v || T.fsOk(v) || v.dataset.tvNoAuto) return false;
    if (document.documentElement.classList.contains('__tvmaxed')) return false;
    if (v.paused || v.muted || v.readyState < 3 || T.area(v) < 0.15) return false;
    const d = v.duration;
    if (!(d === Infinity || d > 90)) return false;
    if (d !== Infinity && v.currentTime < 2) return false;
    return true;
  };
  // Per i canali in diretta: fa partire il video con l'audio e lo ingrandisce.
  T.kick = () => {
    const v = T.main();
    if (!v || !(v.currentSrc || v.src || v.srcObject)) return false;
    v.muted = false; if (v.volume === 0) v.volume = 1;
    if (v.paused) v.play().catch(() => {});
    if (v.readyState < 2) return false;      // riprova al giro successivo
    return T.maximize();
  };
  window.__tv = T;
})();
"""

# Forza H.264 (decodifica molto più leggera di VP9/AV1 su un Core 2 Duo).
H264_JS = r"""
(() => {
  if (window.__tvH264) return; window.__tvH264 = 1;
  const bad = /vp0?9|av01|av1/i;
  try {
    const MS = window.MediaSource;
    if (MS && MS.isTypeSupported) { const o = MS.isTypeSupported.bind(MS);
      MS.isTypeSupported = t => bad.test(t) ? false : o(t); }
    const cp = HTMLMediaElement.prototype.canPlayType;
    HTMLMediaElement.prototype.canPlayType = function (t) { return bad.test(t) ? '' : cp.call(this, t); };
    const mc = navigator.mediaCapabilities;
    if (mc && mc.decodingInfo) { const o = mc.decodingInfo.bind(mc);
      mc.decodingInfo = c => { const ct = (c && c.video && c.video.contentType) || '';
        return bad.test(ct) ? Promise.resolve({supported:false, smooth:false, powerEfficient:false}) : o(c); }; }
  } catch (e) {}
})();
"""


# --------------------------------------------------------------------------
# Chrome DevTools Protocol: client minimale con thread lettore
# --------------------------------------------------------------------------
class CDP:
    def __init__(self, port, scripts):
        self.port = port
        self.scripts = scripts
        self.ws = None
        self.target_id = None
        self.send_lock = threading.Lock()
        self.conn_lock = threading.Lock()
        self.pending = {}
        self.next_id = 1
        self.crashed = threading.Event()

    def targets(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=3) as r:
            return [t for t in json.load(r)
                    if t.get("type") == "page" and not t.get("url", "").startswith("devtools://")]

    def close_other_pages(self):
        try:
            for t in self.targets():
                if t["id"] != self.target_id:
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{self.port}/json/close/{t['id']}", timeout=3).read()
        except Exception as ex:
            log.debug("close_other_pages: %s", ex)

    def ensure(self):
        if self.ws is not None:
            return
        with self.conn_lock:
            if self.ws is not None:
                return
            pages = self.targets()
            if not pages:
                raise ConnectionError("nessuna pagina CDP")
            t = next((p for p in pages if p["id"] == self.target_id), pages[0])
            ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=5,
                                             suppress_origin=True)
            ws.settimeout(None)
            self.ws, self.target_id = ws, t["id"]
            threading.Thread(target=self._reader, args=(ws,), daemon=True).start()
            log.info("CDP collegato a %s", t.get("url"))
        # sessione nuova: registra gli script per i documenti futuri e per quello attuale
        self.call("Inspector.enable")
        self.call("Page.enable")   # necessario perché gli script restino attivi sulle nuove pagine
        # prima la registrazione di tutti (per le pagine future), poi l'esecuzione sulla pagina
        # attuale; un errore o un ritardo su uno script non deve bloccare gli altri
        for s in self.scripts:
            try:
                self.call("Page.addScriptToEvaluateOnNewDocument", {"source": s}, timeout=20)
            except Exception as ex:
                log.warning("registrazione script fallita: %s", ex)
        for s in self.scripts:
            try:
                self.call("Runtime.evaluate", {"expression": s}, timeout=20)
            except Exception as ex:
                log.warning("script sulla pagina attuale: %s", ex)

    def _reader(self, ws):
        while True:
            try:
                msg = ws.recv()
            except Exception:
                break
            if not msg:
                break
            try:
                data = json.loads(msg)
            except ValueError:
                continue
            mid = data.get("id")
            if mid is not None:
                slot = self.pending.get(mid)
                if slot:
                    slot[1] = data
                    slot[0].set()
            elif data.get("method") == "Inspector.targetCrashed":
                log.warning("renderer in crash")
                self.crashed.set()
            elif data.get("method") == "Inspector.detached":
                break
        if self.ws is ws:
            self.drop()

    def drop(self):
        ws, self.ws = self.ws, None
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        for slot in list(self.pending.values()):
            slot[0].set()

    def call(self, method, params=None, timeout=6):
        self.ensure()
        with self.send_lock:
            mid = self.next_id
            self.next_id += 1
            ev = threading.Event()
            self.pending[mid] = [ev, None]
            try:
                self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            except Exception:
                self.pending.pop(mid, None)
                self.drop()
                raise
        if not ev.wait(timeout):
            self.pending.pop(mid, None)
            raise TimeoutError(method)
        res = self.pending.pop(mid, [None, None])[1]
        if res is None:
            raise ConnectionError("CDP disconnesso")
        if "error" in res:
            raise RuntimeError(f"{method}: {res['error']}")
        return res.get("result", {})

    def eval(self, expr, timeout=6, gesture=False):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                           "awaitPromise": True, "userGesture": gesture},
                      timeout=timeout)
        return r.get("result", {}).get("value")


# --------------------------------------------------------------------------
# Chrome
# --------------------------------------------------------------------------
class Browser:
    def __init__(self, cfg, start_url):
        self.cfg = cfg
        self.start_url = start_url
        self.profile = os.path.expanduser(cfg.get("profile_dir", "~/.config/tvbox-chrome"))
        self.proc = None
        self.started_at = 0.0
        self.dsf = 1.0

    def _mark_clean_exit(self):
        """Evita il fumetto 'Chrome non si è chiuso correttamente' dopo un crash."""
        p = os.path.join(self.profile, "Default", "Preferences")
        try:
            with open(p, encoding="utf-8") as f:
                prefs = json.load(f)
            prefs.setdefault("profile", {}).update({"exit_type": "Normal", "exited_cleanly": True})
            with open(p, "w", encoding="utf-8") as f:
                json.dump(prefs, f)
        except (OSError, ValueError):
            pass

    def kill_stale(self):
        subprocess.run(["pkill", "-f", f"--user-data-dir={self.profile}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)

    def start(self):
        os.makedirs(self.profile, exist_ok=True)
        self._mark_clean_exit()
        c = self.cfg
        args = [
            c.get("chrome_binary", "google-chrome-stable"),
            f"--user-data-dir={self.profile}",
            "--kiosk", "--start-fullscreen", "--window-position=0,0",
            "--no-first-run", "--no-default-browser-check", "--noerrdialogs",
            "--disable-session-crashed-bubble", "--disable-infobars",
            "--password-store=basic",
            "--autoplay-policy=no-user-gesture-required",
            "--enable-spatial-navigation",
            "--overscroll-history-navigation=0", "--disable-pinch",
            "--disable-features=Translate,TranslateUI,MediaRouter,GlobalMediaControls",
            f"--remote-debugging-port={c.get('cdp_port', 9222)}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
        ]
        if c.get("disable_gpu"):
            args.append("--disable-gpu")
        dsf = c.get("device_scale_factor", 1.0)
        dsf = auto_scale_factor() if dsf == "auto" else float(dsf)
        self.dsf = dsf
        if abs(dsf - 1.0) > 0.01:
            args.append(f"--force-device-scale-factor={dsf}")
        args.append(self.start_url)
        logf = open(os.path.join(self.profile, "tvbox-chrome.log"), "ab")
        self.proc = subprocess.Popen(args, stdout=logf, stderr=logf, start_new_session=True)
        self.started_at = time.monotonic()
        log.info("Chrome avviato (pid %s)", self.proc.pid)

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def kill(self):
        if not self.alive():
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(8)
        except Exception:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except Exception:
                pass


MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/130.0.0.0 Mobile Safari/537.36")
# domini pubblicitari bloccati sui siti dell'utente (non sui servizi principali)
AD_BLOCK = ["*doubleclick.net*", "*googlesyndication.com*", "*googleadservices.com*",
            "*adservice.google.*", "*taboola.com*", "*outbrain.com*", "*popads.net*",
            "*popcash.net*", "*propellerads*", "*adsterra*", "*exoclick.com*", "*juicyads*",
            "*amazon-adsystem.com*", "*adnxs.com*", "*pubmatic.com*", "*rubiconproject.com*",
            "*criteo.com*", "*criteo.net*", "*onclickads*", "*hilltopads*", "*a-ads.com*",
            "*popunder*", "*clickadu*", "*adcash*", "*trafficjunky*", "*mgid.com*"]


# statistiche, tracciamento e pubblicità caricati dalle dirette Mediaset ("block_trackers" nel
# config): senza, Canale 5 parte in ~10 s invece di ~14 e salta lo spot iniziale (misurato).
TRACKER_BLOCK = ["*imrworldwide.com*", "*adform.net*", "*permutive.app*", "*permutive.com*",
                 "*googletagmanager.com*", "*google-analytics.com*", "*youbora*", "*npaw*",
                 "*aswpsdkeu.com*", "*doubleclick.net*", "*googlesyndication.com*",
                 "*imasdk.googleapis.com*", "*t.mediaset.it*", "*scorecardresearch*", "*chartbeat*",
                 "*facebook.net*", "*criteo*", "*teads*", "*smartclip*", "*adsrvr*"]


def launcher_js(name):
    try:
        with open(os.path.join(LAUNCHER_DIR, name), encoding="utf-8") as f:
            return f.read()
    except OSError as ex:
        log.warning("%s non disponibile: %s", name, ex)
        return None


def hbbtv_bundle():
    """Simulatore HbbTV (launcher/hbbtv.js) + hls.js, iniettati in ogni pagina ma attivi solo
    quando lo user agent è quello di un televisore HbbTV (servizi con "hbbtv": true)."""
    try:
        with open(os.path.join(LAUNCHER_DIR, "vendor", "hls.min.js"), encoding="utf-8") as f:
            hls = f.read()
        with open(os.path.join(LAUNCHER_DIR, "hbbtv.js"), encoding="utf-8") as f:
            hbb = f.read()
    except OSError as ex:
        log.warning("simulatore HbbTV non disponibile: %s", ex)
        return None
    return ("(function(){if(!/HbbTV\\//.test(navigator.userAgent))return;\n"
            + hls + "\n;\n" + hbb + "\n}).call(window);")


# --------------------------------------------------------------------------
# Logica TV
# --------------------------------------------------------------------------
class TV:
    def __init__(self, cfg):
        self.cfg = cfg
        port = cfg.get("http_port", 8765)
        self.launcher_url = f"http://127.0.0.1:{port}/"
        scripts = [HELPER_JS] + ([H264_JS] if cfg.get("force_h264", True) else [])
        # tastiera a schermo + navigazione assistita + meno popup, disponibili in ogni sito
        for name in ("osk.js", "nav.js", "shield.js"):
            js = launcher_js(name)
            if js:
                scripts.append(js)
        hbb = hbbtv_bundle()                 # per ultimo: è il più pesante
        if hbb:
            scripts.append(hbb)
        self.cdp = CDP(cfg.get("cdp_port", 9222), scripts)
        self.browser = Browser(cfg, self.launcher_url)
        self.services = cfg["services"]
        self.actions = queue.Queue()
        self.mouse_mode = False
        self.current = None          # id del servizio aperto dal launcher
        self.opened_url = None
        self.default_ua = None
        self._player_cache = (0.0, False)
        self.shield_script = None     # id dello script che accende shield.js
        self.view_override = False    # vista "telefono" attiva
        self.video_mode = (cfg.get("video_mode") or "").strip()   # es. "1280x720"; vuoto = spento
        self.lowres = False           # schermo in risoluzione "video"
        self._player_since = 0.0
        self._noplayer_since = 0.0
        self._screen_trial = None     # prova di risoluzione in corso: (modo provato, modo di prima, timer)
        self.panel = False            # pannello rapido aperto sopra una diretta
        self._blocked = []            # indirizzi bloccati in Chrome adesso
        self.kbd = UInput({E.EV_KEY: [E.KEY_UP, E.KEY_DOWN, E.KEY_LEFT, E.KEY_RIGHT, E.KEY_ENTER,
                                      E.KEY_ESC, E.KEY_SPACE, E.KEY_TAB, E.KEY_BACKSPACE]},
                          name="tvbox-keyboard")
        self.mouse = UInput({E.EV_KEY: [E.BTN_LEFT, E.BTN_RIGHT],
                             E.EV_REL: [E.REL_X, E.REL_Y, E.REL_WHEEL]}, name="tvbox-mouse")

    # ---------- utilità ----------
    def post(self, fn, *args):
        self.actions.put((fn, args))

    def worker(self):
        while True:
            fn, args = self.actions.get()
            try:
                fn(*args)
            except Exception as ex:
                log.warning("azione %s fallita: %s", getattr(fn, "__name__", fn), ex)

    @staticmethod
    def assisted(s):
        """Navigazione assistita (frecce tra gli elementi cliccabili) per i siti normali;
        no per le app TV (HbbTV, YouTube TV) che gestiscono già il telecomando."""
        return s.get("assist", not (s.get("hbbtv") or s.get("back") == "key"))

    def click_at(self, x, y):
        """Clic "vero" (come col mouse) nel punto x,y della pagina, tramite Chrome."""
        base = {"x": x, "y": y, "button": "left", "clickCount": 1}
        self.cdp.call("Input.dispatchMouseEvent", dict(base, type="mouseMoved", button="none"))
        self.cdp.call("Input.dispatchMouseEvent", dict(base, type="mousePressed"))
        self.cdp.call("Input.dispatchMouseEvent", dict(base, type="mouseReleased"))

    def tv_key(self, code):
        """Tasto con codice da televisore (es. 461 = indietro HbbTV), inviato tramite Chrome."""
        for t in ("rawKeyDown", "keyUp"):
            self.cdp.call("Input.dispatchKeyEvent", {"type": t, "windowsVirtualKeyCode": code,
                                                     "nativeVirtualKeyCode": code})

    def key(self, code):
        self.kbd.write(E.EV_KEY, code, 1)
        self.kbd.syn()
        self.kbd.write(E.EV_KEY, code, 0)
        self.kbd.syn()

    def toast(self, msg):
        try:
            self.cdp.eval(f"window.__tv && __tv.toast({json.dumps(msg)})", timeout=2)
        except Exception:
            pass

    def url(self):
        try:
            return self.cdp.eval("location.href", timeout=3) or ""
        except Exception:
            return ""

    def on_launcher(self, url=None):
        return (url if url is not None else self.url()).startswith(self.launcher_url)

    def service_for(self, url):
        if self.current and self.opened_url and url.startswith(self.opened_url.rstrip("/")):
            return self.services.get(self.current, {})
        host = urlparse(url).hostname or ""
        cur = self.services.get(self.current or "", {})
        if cur.get("url") and urlparse(cur["url"]).hostname == host:
            return cur                               # stesso sito del servizio aperto
        for s in self.services.values():
            if s.get("url") and urlparse(s["url"]).hostname == host:
                return s
        return {}

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

    def volume(self, delta=0):
        ctl = self.cfg.get("mixer_control", "Master")
        if delta:
            subprocess.run(["amixer", "-q", "-M", "sset", ctl,
                            f"{abs(delta)}%{'+' if delta > 0 else '-'}", "unmute"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        out = subprocess.run(["amixer", "-M", "get", ctl], capture_output=True, text=True).stdout
        m = re.search(r"\[(\d+)%\]", out)
        return int(m.group(1)) if m else None

    # ---------- vista telefono / protezione dai popup ----------
    def mobile_ua(self):
        """User agent da smartphone Android con la stessa versione di Chrome installata."""
        if self.default_ua and "X11; Linux x86_64" in self.default_ua:
            return self.default_ua.replace("X11; Linux x86_64", "Linux; Android 14; Pixel 8") \
                                  .replace(" Safari/", " Mobile Safari/")
        return MOBILE_UA

    def set_view(self, s):
        """Vista "telefono" (sito come su uno smartphone, ingrandito a tutto schermo)."""
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
        width = int(self.cfg.get("mobile_width", 800))
        scale = w / width
        self.cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": int(round(h / scale)), "mobile": True,
            "deviceScaleFactor": dpr * scale, "scale": scale})
        self.view_override = True

    def set_shield(self, on):
        """Meno pubblicità e popup: domini pubblicitari bloccati + shield.js acceso."""
        if on and not self.shield_script:
            r = self.cdp.call("Page.addScriptToEvaluateOnNewDocument",
                              {"source": "window.__tvShield = 1;"})
            self.shield_script = r.get("result", r).get("identifier")
        elif not on and self.shield_script:
            self.cdp.call("Page.removeScriptToEvaluateOnNewDocument",
                          {"identifier": self.shield_script})
            self.shield_script = None

    def set_blocked(self, urls):
        """Indirizzi che Chrome non deve caricare (pubblicità dei miei siti, tracciamento Mediaset)."""
        if urls == self._blocked:
            return
        if urls:
            self.cdp.call("Network.enable")
            self.cdp.call("Network.setBlockedURLs", {"urls": urls})
        else:
            self.cdp.call("Network.setBlockedURLs", {"urls": []})
            self.cdp.call("Network.disable")
        self._blocked = urls
        log.info("indirizzi bloccati: %d", len(urls))

    # ---------- azioni ----------
    def open(self, sid):
        s = self.services.get(sid)
        if not s or not s.get("url"):
            return
        log.info("apro %s", sid)
        self.panel = False
        self.mouse_mode = False
        ua = s.get("user_agent") or (self.mobile_ua() if s.get("mobile") else None) or self.default_ua
        # stringa vuota = nessun travestimento (identità normale di Chrome)
        self.cdp.call("Emulation.setUserAgentOverride", {"userAgent": ua or ""})
        try:
            self.set_view(s)
            self.set_shield(bool(s.get("shield")))
            self.set_blocked((AD_BLOCK if s.get("shield") else []) +
                             (TRACKER_BLOCK if s.get("block_trackers") else []))
        except Exception as ex:
            log.warning("vista/protezione: %s", ex)
        self.current, self.opened_url = sid, s["url"]
        self.cdp.call("Page.navigate", {"url": s["url"]})
        if s.get("live") and not s.get("hbbtv"):
            threading.Thread(target=self._kick_live, daemon=True).start()

    def open_url(self, url):
        """Apre un indirizzo scelto dall'utente (I miei siti)."""
        u = normalize_url(url)
        if not u:
            return
        saved = next((x for x in sites_load() if x["url"] == u), {})
        self.services["__sito"] = {"label": urlparse(u).hostname, "url": u,
                                   "auto_fullscreen": True, "shield": True,
                                   "mobile": bool(saved.get("mobile"))}
        self.open("__sito")

    def _kick_live(self):
        deadline = time.monotonic() + 30
        time.sleep(3)
        while time.monotonic() < deadline:
            try:
                if self.cdp.eval("!!(window.__tv && __tv.kick())", timeout=4, gesture=True):
                    return
            except Exception:
                pass
            time.sleep(1.5)

    # ---------- risoluzione durante i video ----------
    def _refit_window(self):
        """Dopo il cambio di risoluzione la finestra di Chrome deve riempire il nuovo schermo."""
        try:
            wid = self.cdp.call("Browser.getWindowForTarget").get("windowId")
            self.cdp.call("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
            self.cdp.call("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "fullscreen"}})
        except Exception as ex:
            log.debug("adattamento finestra: %s", ex)

    def set_lowres(self, on):
        if not self.video_mode or on == self.lowres:
            return
        if self._screen_trial:
            return                    # durante la prova di una risoluzione non si tocca
        if xr_set(self.video_mode if on else full_mode()):
            self.lowres = on
            time.sleep(1.5)
            self._refit_window()

    # ---------- risoluzione scelta in Impostazioni ----------
    def screen_info(self):
        out, cur, pref, modes = xr_query()
        uniq = []
        for m in modes:
            if m not in uniq:
                uniq.append(m)
        return {"output": out, "current": f"{cur[0]}x{cur[1]}" if cur else None,
                "preferred": pref, "saved": screen_saved(), "modes": uniq,
                "video_mode": self.video_mode, "video_low": screen_video_low(),
                "trial": bool(self._screen_trial)}

    def screen_video(self, on):
        screen_save(video_low=on)
        log.info("risoluzione bassa nei video: %s", on)
        if not on:
            self.set_lowres(False)

    def screen_try(self, mode):
        """Prova una risoluzione: se entro 15 s non arriva "keep", torna a quella di prima."""
        if self._screen_trial:
            self._screen_trial[2].cancel()
            prev = self._screen_trial[1]
        else:
            prev = screen_saved()
        if not xr_set(mode):
            self._screen_trial = None
            return
        self.lowres = False
        timer = threading.Timer(15, lambda: self.post(self.screen_revert))
        timer.daemon = True
        self._screen_trial = (mode, prev, timer)
        timer.start()
        time.sleep(1.5)
        self._refit_window()

    def screen_keep(self):
        if not self._screen_trial:
            return
        mode, _, timer = self._screen_trial
        timer.cancel()
        self._screen_trial = None
        screen_save(mode)
        log.info("risoluzione scelta: %s", mode)
        if self.cfg.get("device_scale_factor") == "auto" and abs(auto_scale_factor() - self.browser.dsf) > 0.01:
            log.info("cambia l'ingrandimento: riavvio Chrome")
            self.browser.kill()       # il controllo lo fa ripartire con il valore nuovo

    def screen_revert(self):
        if not self._screen_trial:
            return
        _, prev, timer = self._screen_trial
        timer.cancel()
        self._screen_trial = None
        m = prev if prev == "auto" or prev in xr_query()[3] else "auto"
        log.info("prova non confermata: torno a %s", m)
        xr_set(m)
        time.sleep(1.5)
        self._refit_window()

    def video_res_tick(self, player):
        """Chiamata ogni 2 s dal controllo: 720p dopo 4 s di video, di nuovo pieno dopo 8 s senza."""
        if not self.video_mode:
            return
        if not screen_video_low():
            if self.lowres:
                self.set_lowres(False)
            return
        now = time.monotonic()
        if player:
            self._noplayer_since = 0.0
            self._player_since = self._player_since or now
            if not self.lowres and now - self._player_since >= 4:
                self.set_lowres(True)
        else:
            self._player_since = 0.0
            self._noplayer_since = self._noplayer_since or now
            if self.lowres and now - self._noplayer_since >= 8:
                self.set_lowres(False)

    def home(self, page=None):
        log.info("HOME")
        self.panel = False
        self.set_lowres(False)
        self.mouse_mode = False
        self.current = self.opened_url = None
        self.cdp.call("Emulation.setUserAgentOverride", {"userAgent": self.default_ua or ""})
        try:
            self.set_view({})
            self.set_shield(False)
            self.set_blocked([])
        except Exception as ex:
            log.warning("vista/protezione: %s", ex)
        self.cdp.close_other_pages()
        self.cdp.call("Page.navigate", {"url": self.launcher_url + (f"#{page}" if page else "")})

    # ---------- pannello rapido sopra una diretta ----------
    def is_live_channel(self, url=None):
        s = self.services.get(self.current or "", {})
        return bool(s.get("onair")) and not self.on_launcher(url)

    def panel_active(self):
        if not self.panel:
            return False
        try:
            self.panel = bool(self.cdp.eval("!!(window.__tvp && __tvp.isOpen())", timeout=3))
        except Exception:
            self.panel = False
        return self.panel

    def panel_open(self):
        hidden = set(home_load().get("hidden", []))
        ids = []
        for sec in self.cfg.get("sections", []):
            for sid in sec.get("items", []):
                if self.services.get(sid, {}).get("onair") and sid not in hidden and sid not in ids:
                    ids.append(sid)
        try:
            od = onair(self.services)
        except Exception:
            od = {}
        chans = []
        for sid in ids:
            s, o = self.services[sid], od.get(self.services[sid]["onair"]) or {}
            chans.append({"id": sid, "label": s.get("label", sid), "color": s.get("color"),
                          "title": o.get("title", ""), "start": o.get("start", 0),
                          "end": o.get("end", 0), "image": o.get("image", ""),
                          "desc": (o.get("desc") or "")[:300]})
        data = {"channels": chans, "current": self.current, "vol": self.volume(0),
                "videoLow": screen_video_low() if self.video_mode else None}
        js = launcher_js("panel.js")
        self.panel = bool(self.cdp.eval(f"{js}\n;window.__tvp.open({json.dumps(data)})", timeout=6))
        log.info("pannello rapido: %s", "aperto" if self.panel else "non riuscito")

    def _panel_reopen(self, sid, old_url):
        """Dopo il cambio di canale riapre il pannello sulla pagina nuova (se si sta ancora lì)."""
        deadline = time.monotonic() + 15
        time.sleep(1.5)
        while time.monotonic() < deadline:
            if self.current != sid:
                return
            try:
                if self.cdp.eval("location.href", timeout=3) != old_url and \
                        self.cdp.eval("document.readyState", timeout=3) in ("interactive", "complete"):
                    time.sleep(1.2)
                    if self.current == sid and not self.panel:
                        self.post(self.panel_open)
                    return
            except Exception:
                pass
            time.sleep(0.5)

    def panel_close(self):
        self.panel = False
        try:
            self.cdp.eval("window.__tvp && __tvp.close()", timeout=3)
        except Exception:
            pass

    def panel_ok(self):
        r = self.cdp.eval("window.__tvp ? __tvp.ok() : null", timeout=3)
        if not isinstance(r, dict):
            return
        a = r.get("act")
        if a == "open":
            sid = r.get("id")
            if sid == self.current:
                self.panel_close()
                return
            # il pannello resta: segno la scheda "Apro…", cambio canale e lo riapro sul nuovo
            self.cdp.eval(f"window.__tvp && __tvp.set('busy', {json.dumps(sid)})", timeout=3)
            old = self.url()
            self.open(sid)
            threading.Thread(target=self._panel_reopen, args=(sid, old), daemon=True).start()
        elif a == "vol":
            v = self.volume(int(r.get("d", 0)))
            self.cdp.eval(f"window.__tvp && __tvp.set('vol', {json.dumps(v)})", timeout=3)
        elif a == "video":
            on = bool(r.get("on"))
            self.screen_video(on)
            self.cdp.eval(f"window.__tvp && __tvp.set('videoLow', {json.dumps(on)})", timeout=3)
        elif a == "settings":
            self.home("settings")
        elif a == "home":
            self.home()

    def back(self):
        if self.panel_active():
            self.panel_close()
            return
        if self.mouse_mode:
            self.mouse_mode = False
            self.toast("Puntatore disattivato")
            return
        url = self.url()
        if self.on_launcher(url):
            self.key(E.KEY_ESC)                      # gestito dal launcher
            return
        if self.is_live_channel(url):                # diretta: pannello con canali e impostazioni
            self.panel_open()
            return
        if self.cdp.eval("!!(window.__nav && __nav.back())", timeout=3):
            return                                   # chiusa la tastiera a schermo
        s = self.service_for(url)
        if s.get("live") and self.current:          # canale in diretta: torna al launcher
            self.home()
            return
        if s.get("hbbtv"):                           # app per TV: gestisce lei "indietro"
            self.tv_key(461)
            return
        if s.get("back") == "key":                   # app TV (YouTube) gestiscono da sole Esc
            self.key(E.KEY_ESC)
            return
        if self.cdp.eval("!!(window.__tv && __tv.exitFull())", timeout=3):
            return
        can_back = self.cdp.eval("history.length > 1", timeout=3)
        if can_back:
            self.cdp.eval("history.back()", timeout=3)
        else:
            self.home()

    def ok(self):
        if self.panel_active():
            self.panel_ok()
            return
        if self.mouse_mode:
            self.click()
            return
        url = self.url()
        if not self.on_launcher(url) and self.service_for(url).get("player_keys", True) \
                and self.is_player():
            self.cdp.eval("window.__tv && __tv.toggle()", timeout=3, gesture=True)
            return
        if not self.on_launcher(url) and self.assisted(self.service_for(url)):
            r = self.cdp.eval("window.__nav ? __nav.activate() : null", timeout=4, gesture=True)
            if isinstance(r, dict) and "x" in r:
                self.click_at(r["x"], r["y"])
                return
            if r:
                return
        self.key(E.KEY_ENTER)

    def play_pause(self):
        if self.panel_active():
            self.panel_close()
            return
        if self.services.get(self.current or "", {}).get("hbbtv"):
            self.tv_key(463)                         # VK_PLAY_PAUSE
            return
        if not self.cdp.eval("!!(window.__tv && __tv.toggle())", timeout=3, gesture=True):
            self.key(E.KEY_SPACE)

    def toggle_mouse(self):
        self.mouse_mode = not self.mouse_mode
        self.toast("Puntatore attivo: frecce per muovere, OK per cliccare"
                   if self.mouse_mode else "Puntatore disattivato")
        if self.mouse_mode:                           # piccolo movimento per mostrarlo
            self.move(1, 1)

    def move(self, dx, dy):
        if dx:
            self.mouse.write(E.EV_REL, E.REL_X, dx)
        if dy:
            self.mouse.write(E.EV_REL, E.REL_Y, dy)
        self.mouse.syn()

    def move_dir(self, d, px):
        self.move({"left": -px, "right": px}.get(d, 0), {"up": -px, "down": px}.get(d, 0))

    def click(self):
        self.mouse.write(E.EV_KEY, E.BTN_LEFT, 1)
        self.mouse.syn()
        self.mouse.write(E.EV_KEY, E.BTN_LEFT, 0)
        self.mouse.syn()

    def arrow(self, d, repeat_count):
        if self.panel and self.panel_active():
            if d in ("up", "down"):                  # + e − del telecomando: volume
                step = int(self.cfg.get("volume_step", 5))
                v = self.volume(step if d == "up" else -step)
                self.cdp.eval(f"window.__tvp && __tvp.set('vol', {json.dumps(v)})", timeout=3)
            else:
                self.cdp.eval(f"window.__tvp && __tvp.move({json.dumps(d)})", timeout=3)
            return
        if self.mouse_mode:                           # pressione breve: piccolo passo
            self.move_dir(d, int(self.cfg.get("pointer_nudge_px", 12)))
            return
        url = self.url() if repeat_count == 0 else (self.opened_url or "")
        if url and not self.on_launcher(url) and self.service_for(url).get("player_keys", True) \
                and self.is_player():
            if d in ("up", "down"):
                step = int(self.cfg.get("volume_step", 5))
                v = self.volume(step if d == "up" else -step)
                if v is not None:
                    self.toast(f"🔊  Volume {v}%")
            else:
                sec = -int(self.cfg.get("seek_back_s", 10)) if d == "left" \
                    else int(self.cfg.get("seek_forward_s", 30))
                self.cdp.eval(f"window.__tv && __tv.seek({sec})", timeout=3)
            return
        if url and not self.on_launcher(url) and self.assisted(self.service_for(url)):
            if self.cdp.eval(f"window.__nav ? __nav.move({json.dumps(d)}) : null", timeout=4):
                return
        self.key({"up": E.KEY_UP, "down": E.KEY_DOWN, "left": E.KEY_LEFT, "right": E.KEY_RIGHT}[d])

    def auto_fullscreen_tick(self):
        if not self.current:
            url = self.url()
            if self.on_launcher(url):
                return
            s = self.service_for(url)
        else:
            s = self.services.get(self.current, {})
        if s.get("hbbtv") or not (s.get("auto_fullscreen") or s.get("live")):
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
                self._blocked = []                   # Chrome nuovo: niente blocchi attivi
                log.warning("Chrome non attivo: riavvio")
                self.browser.start()
                fails = 0
                time.sleep(5)
                continue
            try:
                self.cdp.eval("1", timeout=8)
                fails = 0
                if self.default_ua is None:
                    # identità vera di Chrome (non quella eventualmente "travestita" da TV)
                    ua = self.cdp.call("Browser.getVersion", timeout=3).get("userAgent", "")
                    if ua and "HbbTV" not in ua:
                        self.default_ua = ua.replace("HeadlessChrome", "Chrome")
                if self.cdp.crashed.is_set():
                    self.cdp.crashed.clear()
                    self.home()
                self.auto_fullscreen_tick()
                if self.video_mode:
                    url = self.url()
                    self.video_res_tick(not self.on_launcher(url) and self.is_player())
                if self.shield_script:               # popup in nuove schede: chiusi
                    self.cdp.close_other_pages()
            except Exception as ex:
                grace = time.monotonic() - self.browser.started_at < 60
                if not grace:
                    fails += 1
                    log.warning("Chrome non risponde (%d): %s", fails, ex)
                    if fails >= 4:
                        log.error("Chrome bloccato: lo termino")
                        self.cdp.drop()
                        self.browser.kill()
                        fails = 0
            time.sleep(2)


# --------------------------------------------------------------------------
# Apple Remote
# --------------------------------------------------------------------------
ARROWS = {E.KEY_VOLUMEUP: "up", E.KEY_VOLUMEDOWN: "down", E.KEY_BACK: "left",
          E.KEY_FORWARD: "right", E.KEY_UP: "up", E.KEY_DOWN: "down",
          E.KEY_LEFT: "left", E.KEY_RIGHT: "right"}


class Remote(threading.Thread):
    def __init__(self, tv):
        super().__init__(daemon=True)
        self.tv = tv
        self.long_s = tv.cfg.get("long_press_ms", 800) / 1000.0
        self.repeat_s = tv.cfg.get("arrow_repeat_ms", 170) / 1000.0
        # il telecomando Apple prolunga anche le pressioni brevi: la ripetizione parte solo
        # se la freccia resta premuta almeno questo tempo (altrimenti 1 pressione = 2-3 passi)
        self.repeat_delay_s = tv.cfg.get("arrow_repeat_delay_ms", 600) / 1000.0
        self.press_t = 0.0
        # puntatore: OK tenuto a lungo lo attiva (più lungo degli altri tasti, perché il
        # telecomando a volte allunga un click normale); velocità costante, niente accelerazione
        self.mouse_toggle_s = tv.cfg.get("mouse_toggle_ms", 1500) / 1000.0
        self.pointer_speed = float(tv.cfg.get("pointer_speed_px_s", 640))
        self.pointer_delay_s = tv.cfg.get("pointer_delay_ms", 300) / 1000.0
        self.aluminium = False
        self.timers = {}
        self.long_fired = {}
        self.rep = 0
        self.last_rep = 0.0
        # il ricevitore a infrarossi a volte "spezza" una pressione in due (rilascio e nuova
        # pressione a pochi ms): una nuova pressione così vicina al rilascio è la stessa
        self.debounce_s = tv.cfg.get("arrow_debounce_ms", 220) / 1000.0
        self.last_up = {}
        self.ghost = None
        self.nrep = 0

    def find(self):
        match = [m.lower() for m in self.tv.cfg.get("remote_match", ["IR Receiver"])]
        for path in evdev.list_devices():
            try:
                d = evdev.InputDevice(path)
            except OSError:
                continue
            if d.name.startswith("tvbox-"):
                d.close()
                continue
            if any(m in d.name.lower() for m in match):
                return d
            d.close()
        return None

    def run(self):
        while True:
            dev = self.find()
            if not dev:
                log.info("telecomando non trovato, riprovo...")
                time.sleep(5)
                continue
            log.info("telecomando: %s (%s)", dev.name, dev.path)
            try:
                dev.grab()
            except OSError as ex:
                log.warning("grab fallito: %s", ex)
            try:
                for ev in dev.read_loop():
                    if ev.type == E.EV_KEY:
                        self.handle(ev.code, ev.value)
            except OSError as ex:
                log.warning("telecomando perso: %s", ex)
            finally:
                try:
                    dev.close()
                except Exception:
                    pass
            time.sleep(1)

    def _logical(self, code):
        if code == E.KEY_ENTER:
            self.aluminium = True
            return "ok"
        if code == E.KEY_PLAYPAUSE:
            return "play" if self.aluminium else "ok"
        if code in (E.KEY_MENU, E.KEY_ESC):
            return "menu"
        if code in (E.KEY_HOME, E.KEY_HOMEPAGE):
            return "home"
        return None

    def handle(self, code, val):
        tv = self.tv
        now = time.monotonic()
        if code in ARROWS:
            d = ARROWS[code]
            if val == 0:
                self.last_up[code] = now
                log.info("freccia %s rilasciata dopo %d ms (%d ripetizioni)%s", d,
                         (now - self.press_t) * 1000, self.nrep, " [doppione]" if self.ghost == code else "")
                self.ghost = None
                return
            if val == 1 and now - self.last_up.get(code, -9) < self.debounce_s:
                self.ghost = code                    # doppione: ignorato fino al rilascio
                self.nrep = 0
                return
            if self.ghost == code:
                self.nrep += 1
                return
            if val == 1:
                self.rep, self.last_rep, self.press_t, self.nrep = 0, now, now, 0
                tv.post(tv.arrow, d, 0)
                return
            self.nrep += 1
            if val == 2 and tv.mouse_mode:
                if now - self.press_t < self.pointer_delay_s:
                    return
                # primo passo dopo l'attesa: intervallo tipico di ripetizione (~33 ms)
                dt = 0.033 if self.last_rep <= self.press_t else min(now - self.last_rep, 0.1)
                self.last_rep = now
                px = max(1, round(self.pointer_speed * dt))
                tv.post(tv.move_dir, d, px)
            elif val == 2:
                if now - self.press_t < self.repeat_delay_s:
                    return
                self.rep += 1
                if tv.mouse_mode or now - self.last_rep >= self.repeat_s:
                    self.last_rep = now
                    tv.post(tv.arrow, d, self.rep)
            return
        name = self._logical(code)
        if not name:
            return
        if name == "home":
            if val == 1:
                tv.post(tv.home)
            return
        if val == 1:
            self.long_fired[name] = False
            t = threading.Timer(self.mouse_toggle_s if name == "ok" else self.long_s,
                                self._long, args=(name,))
            self.timers[name] = t
            t.start()
        elif val == 0:
            t = self.timers.pop(name, None)
            if t:
                t.cancel()
            if not self.long_fired.get(name):
                tv.post({"ok": tv.ok, "menu": tv.back, "play": tv.play_pause}[name])

    def _long(self, name):
        self.long_fired[name] = True
        tv = self.tv
        if name == "menu":
            tv.post(tv.home)
        elif name == "ok":
            tv.post(tv.toggle_mouse)


# --------------------------------------------------------------------------
# Wi-Fi (Impostazioni > Wi-Fi): dialoga con wpa_supplicant@<scheda> tramite wpa_cli.
# L'utente tv è nel gruppo netdev, quindi non servono privilegi di root.
# --------------------------------------------------------------------------
WPA_CLI = "/usr/sbin/wpa_cli"
wifi_lock = threading.Lock()


def wifi_iface():
    try:
        for n in sorted(os.listdir("/sys/class/net")):
            if os.path.isdir(f"/sys/class/net/{n}/wireless"):
                return n
    except OSError:
        pass
    return None


def _wpa(iface, *args, timeout=8):
    r = subprocess.run([WPA_CLI, "-i", iface, *args], capture_output=True,
                       text=True, timeout=timeout)
    return r.stdout.strip()


def _unescape_ssid(s):
    """wpa_cli stampa i nomi rete con escape stile C (\\xNN, \\\", \\\\)."""
    out, i = bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n == "x" and i + 3 < len(s):
                try:
                    out.append(int(s[i + 2:i + 4], 16))
                    i += 4
                    continue
                except ValueError:
                    pass
            out += {"n": b"\n", "r": b"\r", "t": b"\t", "e": b"\x1b"}.get(n, n.encode())
            i += 2
            continue
        out += c.encode()
        i += 1
    return out.decode("utf-8", "replace")


def _ipv4(iface):
    r = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", iface],
                       capture_output=True, text=True).stdout
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", r)
    return m.group(1) if m else None


def _saved(iface):
    nets = {}
    for line in _wpa(iface, "list_networks").splitlines()[1:]:
        f = line.split("\t")
        if len(f) >= 2 and f[0].isdigit():
            nets[_unescape_ssid(f[1])] = f[0]
    return nets


def wifi_status():
    iface = wifi_iface()
    if not iface:
        return {"present": False}
    try:
        st = dict(l.split("=", 1) for l in _wpa(iface, "status").splitlines() if "=" in l)
    except Exception as ex:
        return {"present": True, "iface": iface, "error": f"wpa_supplicant non risponde ({ex})"}
    if not st:
        return {"present": True, "iface": iface, "error": "wpa_supplicant non attivo"}
    res = {"present": True, "iface": iface, "state": st.get("wpa_state"),
           "connected": st.get("wpa_state") == "COMPLETED",
           "ssid": _unescape_ssid(st.get("ssid", "")) or None, "ip": _ipv4(iface)}
    if res["connected"]:
        m = re.search(r"RSSI=(-?\d+)", _wpa(iface, "signal_poll"))
        if m:
            res["signal"] = int(m.group(1))
    return res


def wifi_scan():
    iface = wifi_iface()
    if not iface:
        return {"error": "Nessuna scheda Wi-Fi"}
    with wifi_lock:
        _wpa(iface, "scan")
        # la scansione di tutti i canali può durare parecchi secondi: aspetto che
        # l'elenco smetta di crescere (minimo 3 s, massimo 10 s)
        lines, prev, t0 = [], -1, time.monotonic()
        while time.monotonic() - t0 < 10:
            time.sleep(1)
            lines = _wpa(iface, "scan_results").splitlines()[1:]
            if time.monotonic() - t0 >= 3 and len(lines) == prev and lines:
                break
            prev = len(lines)
        best = {}
        for line in lines:
            f = line.split("\t")
            if len(f) < 5 or not f[4]:
                continue                                   # rete nascosta
            ssid, sig, flags = _unescape_ssid(f[4]), int(f[2]), f[3]
            if ssid not in best or sig > best[ssid]["signal"]:
                best[ssid] = {"ssid": ssid, "signal": sig,
                              "secure": "WPA" in flags or "RSN" in flags or "WEP" in flags,
                              "wep": "WEP" in flags and "WPA" not in flags}
        saved = _saved(iface)
    for n in best.values():
        n["saved"] = n["ssid"] in saved
    return {"networks": sorted(best.values(), key=lambda n: -n["signal"])}


def wifi_connect(ssid, password):
    """Collega alla rete. Se fallisce ricarica la configurazione salvata (nulla cambia)."""
    iface = wifi_iface()
    if not iface or not ssid:
        return {"ok": False, "error": "Nessuna scheda Wi-Fi"}
    if password and not 8 <= len(password) <= 63:
        return {"ok": False, "error": "La password deve avere da 8 a 63 caratteri"}
    with wifi_lock:
        saved = _saved(iface)
        nid = saved.get(ssid)
        if nid is None or password:
            if nid is None:
                nid = _wpa(iface, "add_network")
                if not nid.isdigit():
                    return {"ok": False, "error": "wpa_supplicant non risponde"}
            raw = ssid.encode()
            _wpa(iface, "set_network", nid, "ssid", raw.hex())
            if password:
                # chiave derivata (come wpa_passphrase): la password in chiaro non va su disco
                psk = hashlib.pbkdf2_hmac("sha1", password.encode(), raw, 4096, 32).hex()
                _wpa(iface, "set_network", nid, "key_mgmt", "WPA-PSK")
                _wpa(iface, "set_network", nid, "psk", psk)
            else:
                _wpa(iface, "set_network", nid, "key_mgmt", "NONE")
            _wpa(iface, "set_network", nid, "scan_ssid", "1")
        _wpa(iface, "select_network", nid)
        ok, deadline = False, time.monotonic() + 30
        while time.monotonic() < deadline:
            time.sleep(1)
            st = dict(l.split("=", 1) for l in _wpa(iface, "status").splitlines() if "=" in l)
            if st.get("wpa_state") == "COMPLETED" and _unescape_ssid(st.get("ssid", "")) == ssid:
                ok = True
                break
        if not ok:
            _wpa(iface, "reconfigure")                     # torna alle reti salvate
            log.warning("wifi: collegamento a %r fallito", ssid)
            return {"ok": False, "error": "Collegamento non riuscito: password sbagliata "
                                          "o rete troppo lontana"}
        _wpa(iface, "enable_network", "all")               # le altre reti restano di riserva
        _wpa(iface, "save_config")
        ip = None
        for _ in range(15):
            ip = _ipv4(iface)
            if ip:
                break
            time.sleep(1)
        log.info("wifi: collegato a %r (%s)", ssid, ip)
        return {"ok": True, "ssid": ssid, "ip": ip}


def wifi_forget(ssid):
    iface = wifi_iface()
    if not iface:
        return {"ok": False}
    with wifi_lock:
        nid = _saved(iface).get(ssid)
        if nid is not None:
            _wpa(iface, "remove_network", nid)
            _wpa(iface, "save_config")
            _wpa(iface, "reassociate")
    return {"ok": True}


# --------------------------------------------------------------------------
# "I miei siti": indirizzi scelti dall'utente, salvati nella sua cartella
# --------------------------------------------------------------------------
SITES_PATH = os.path.expanduser("~/.config/tvbox/siti.json")
sites_lock = threading.Lock()


def normalize_url(u):
    u = (u or "").strip()
    if not u:
        return None
    if not re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I):
        u = "https://" + u
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname:
        return None
    return u


def sites_load():
    try:
        with open(SITES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return [x for x in data if isinstance(x, dict) and x.get("url")]
    except (OSError, ValueError):
        return []


def sites_save(lst):
    os.makedirs(os.path.dirname(SITES_PATH), exist_ok=True)
    tmp = SITES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lst, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, SITES_PATH)


HOME_PATH = os.path.expanduser("~/.config/tvbox/home.json")


def home_load():
    try:
        with open(HOME_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return {"hidden": [x for x in d.get("hidden", []) if isinstance(x, str)]}
    except (OSError, ValueError, AttributeError):
        return {"hidden": []}


def home_api(q):
    """Tile nascoste dalla schermata iniziale / da Altri servizi (scelte dall'utente)."""
    with sites_lock:
        h = home_load()
        sid, a = q.get("id", ""), q.get("action")
        if sid and sid != "impostazioni" and a in ("hide", "show"):
            hidden = [x for x in h["hidden"] if x != sid] + ([sid] if a == "hide" else [])
            h = {"hidden": hidden}
            os.makedirs(os.path.dirname(HOME_PATH), exist_ok=True)
            tmp = HOME_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(h, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, HOME_PATH)
    return h


def sites_api(q):
    a = q.get("action", "list")
    with sites_lock:
        lst = sites_load()
        if a == "add":
            u = normalize_url(q.get("url"))
            if not u:
                return {"ok": False, "error": "Indirizzo non valido"}
            label = (q.get("label") or urlparse(u).hostname or u).strip()[:40]
            lst = [x for x in lst if x["url"] != u] + [{"label": label, "url": u}]
            sites_save(lst)
        elif a == "remove":
            lst = [x for x in lst if x["url"] != q.get("url")]
            sites_save(lst)
        elif a == "mobile":                          # vista telefono sì/no
            for x in lst:
                if x["url"] == q.get("url"):
                    x["mobile"] = q.get("on") == "1"
            sites_save(lst)
        elif a == "home":                            # metti / togli dalla schermata iniziale
            for x in lst:
                if x["url"] == q.get("url"):
                    x["home"] = q.get("on") == "1"
            sites_save(lst)
    return {"ok": True, "sites": lst}


# --------------------------------------------------------------------------
# Programmi in onda sui canali Rai (per le schede "Canali in diretta")
# --------------------------------------------------------------------------
_onair = {"t": 0.0, "data": {}}


def _rai_onair():
    """Palinsesto Rai: {"rai:Rai 1": {...}, ...}"""
    out = {}
    d = _get_json("https://www.raiplay.it/palinsesto/onAir.json")
    now = time.localtime()
    for c in d.get("on_air", []):
        ci = c.get("currentItem") or {}
        img = (ci.get("images") or {}).get("landscape") or ci.get("image") or ""
        m = re.match(r"(\d+):(\d+)", ci.get("duration") or "")
        h = re.match(r"(\d+):(\d+)", ci.get("hour") or "")
        start = end = 0
        if h:
            st = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, int(h.group(1)), int(h.group(2)),
                              0, 0, 0, -1))
            if st > time.time() + 60:
                st -= 86400                          # iniziato ieri sera
            start = int(st * 1000)
            end = start + ((int(m.group(1)) * 60 + int(m.group(2))) * 60000 if m else 0)
        out["rai:" + c.get("channel", "")] = {
            "title": (ci.get("program") or {}).get("name") or ci.get("name") or "",
            "desc": ci.get("description") or "",
            "start": start, "end": end,
            "image": ("https://www.raiplay.it/cropgd/480x270" + img) if img.startswith("/") else "",
            "image_big": ("https://www.raiplay.it/cropgd/1280x720" + img) if img.startswith("/") else ""}
    return out


def _mediaset_onair(code):
    d = _get_json(f"https://static3.mediasetplay.mediaset.it/apigw/nownext/{code}.json")
    r = d.get("response") or {}
    cl = r.get("currentListing") or {}
    # il file viene aggiornato con ritardo: se il programma "attuale" è già finito, è il successivo
    if (cl.get("endTime") or 0) < time.time() * 1000 and r.get("nextListing"):
        cl = r["nextListing"]
    p = cl.get("program") or {}
    img, best, big, bw = "", 0, "", 0
    for k, v in (p.get("thumbnails") or {}).items():
        w = v.get("width") or 0
        if "keyframe" not in k or not v.get("url"):
            continue
        if not img or (360 <= w < best) or best < 360 < w:   # scheda: la più piccola da 360 px in su
            img, best = v["url"], w
        if w <= 1920 and w > bw:                             # salvaschermo: la più grande fino a 1920
            big, bw = v["url"], w
    return {"title": cl.get("mediasetlisting$epgTitle") or p.get("title") or "",
            "desc": cl.get("description") or p.get("description") or "",
            "start": cl.get("startTime") or 0, "end": cl.get("endTime") or 0, "image": img,
            "image_big": big or img}


_wbd = {}


def _wbd_onair(env):
    """Palinsesto dei canali Warner Bros. Discovery (Real Time, DMAX, Nove) dalla
    "Guida TV" pubblica dei loro siti. Il palinsesto si riscarica ogni 30 minuti."""
    c = _wbd.get(env)
    if not c or time.monotonic() - c["t"] > 1800:
        d = _get_json("https://public.aurora.enhanced.live/site/page/guida-tv/?include=default"
                      f"&filter%5Benvironment%5D={env}&v=2", timeout=10)
        progs = []

        def walk(o):
            if isinstance(o, dict):
                if o.get("type") == "epgBlock":
                    for ch in o.get("channels") or []:
                        for day in ch.get("days") or []:
                            progs.extend(p for p in day.get("programs") or [] if p.get("start_dt"))
                    return
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(d)
        c = _wbd[env] = {"t": time.monotonic(), "progs": progs}
    now = time.time()
    for p in c["progs"]:
        try:
            # orari in UTC ("+00:00"): calendar.timegm non dipende da fuso e ora legale
            st = calendar.timegm(time.strptime(p["start_dt"][:19], "%Y-%m-%dT%H:%M:%S"))
            en = calendar.timegm(time.strptime(p["end_dt"][:19], "%Y-%m-%dT%H:%M:%S"))
        except (KeyError, ValueError):
            continue
        if st <= now < en and (p.get("title") or p.get("show_name")):
            show, ep = p.get("show_name") or "", p.get("title") or ""
            desc = p.get("description") or ""
            if show and ep and ep != show:
                desc = f"{ep}. {desc}" if desc else ep
            return {"title": show or ep, "desc": desc, "start": int(st * 1000), "end": int(en * 1000),
                    "image": p.get("show_image") or ""}
    return {}


def onair(services):
    """Programmi in onda per le schede "Canali in diretta" (chiavi "rai:<canale>" o "ms:<sigla>")."""
    if time.monotonic() - _onair["t"] < 60:
        return _onair["data"]
    data = dict(_onair["data"])
    keys = {s.get("onair") for s in services.values() if s.get("onair")}
    if any(k.startswith("rai:") for k in keys):
        try:
            data.update(_rai_onair())
        except Exception as ex:
            log.warning("palinsesto Rai non disponibile: %s", ex)
    for k in keys:
        if k.startswith("wbd:"):
            try:
                data[k] = _wbd_onair(k[4:])
            except Exception as ex:
                log.warning("palinsesto %s non disponibile: %s", k, ex)
        if k.startswith("ms:"):
            try:
                data[k] = _mediaset_onair(k[3:])
            except Exception as ex:
                log.warning("palinsesto Mediaset %s non disponibile: %s", k, ex)
    _onair.update(t=time.monotonic(), data=data)
    return data


# --------------------------------------------------------------------------
# Meteo (Open-Meteo, gratuito e senza registrazione) per la città scelta dall'utente
# --------------------------------------------------------------------------
METEO_PATH = os.path.expanduser("~/.config/tvbox/meteo.json")
_meteo = {"t": 0.0, "data": None}
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


def _get_json(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "tvbox"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def meteo_api(q):
    a = q.get("action", "now")
    if a == "search":                                # cerca la città (solo Italia per prima)
        name = (q.get("q") or "").strip()
        if not name:
            return {"results": []}
        try:
            d = _get_json("https://geocoding-api.open-meteo.com/v1/search?count=6&language=it&format=json&name="
                          + urllib.parse.quote(name))
        except Exception as ex:
            return {"error": f"Ricerca non riuscita ({ex})"}
        res = [{"name": r.get("name"), "area": ", ".join(x for x in (r.get("admin2") or r.get("admin1"),
                                                                     r.get("country")) if x),
                "lat": r.get("latitude"), "lon": r.get("longitude"), "it": r.get("country_code") == "IT"}
               for r in d.get("results", [])]
        res.sort(key=lambda r: not r["it"])
        return {"results": res[:5]}
    if a == "set":
        try:
            city = {"name": q["name"][:40], "lat": float(q["lat"]), "lon": float(q["lon"])}
        except (KeyError, ValueError):
            return {"ok": False}
        os.makedirs(os.path.dirname(METEO_PATH), exist_ok=True)
        with open(METEO_PATH, "w", encoding="utf-8") as f:
            json.dump(city, f, ensure_ascii=False)
        _meteo.update(t=0.0, data=None)
        return {"ok": True, "city": city}
    try:                                             # meteo attuale (aggiornato ogni 15 minuti)
        with open(METEO_PATH, encoding="utf-8") as f:
            city = json.load(f)
    except (OSError, ValueError):
        return {"city": None}
    if _meteo["data"] and _meteo["data"]["city"] == city["name"] and time.monotonic() - _meteo["t"] < 900:
        return _meteo["data"]
    try:
        d = _get_json("https://api.open-meteo.com/v1/forecast?current=temperature_2m,weather_code,is_day"
                      f"&timezone=auto&latitude={city['lat']}&longitude={city['lon']}")["current"]
        text, day_icon, night_icon = WMO.get(int(d.get("weather_code", -1)), ("", "🌡️", "🌡️"))
        data = {"city": city["name"], "temp": round(d.get("temperature_2m", 0)), "text": text,
                "icon": day_icon if d.get("is_day", 1) else night_icon}
    except Exception as ex:
        log.warning("meteo non disponibile: %s", ex)
        return _meteo["data"] or {"city": city["name"], "error": True}
    _meteo.update(t=time.monotonic(), data=data)
    return data


# --------------------------------------------------------------------------
# Loghi dei siti (per i riquadri): l'icona "app" che il sito stesso pubblica,
# scaricata una volta e conservata in ~/.config/tvbox/icons
# --------------------------------------------------------------------------
ICON_DIR = os.path.expanduser("~/.config/tvbox/icons")
DESKTOP_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0 Safari/537.36"
icon_lock = threading.Lock()


def _fetch(url, limit=1_500_000, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": DESKTOP_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit), r.headers.get_content_type()


def _icon_candidates(base):
    """Icone dichiarate dalla pagina, dalla migliore: apple-touch-icon e dimensioni grandi."""
    html, _ = _fetch(base, limit=400_000)
    html = html.decode("utf-8", "replace")
    cands = []
    for tag in re.findall(r"<link\b[^>]*>", html, re.I):
        rel = re.search(r'rel=["\']?([^"\'>]+)', tag, re.I)
        href = re.search(r'href=["\']?([^"\' >]+)', tag, re.I)
        if not rel or not href or "icon" not in rel.group(1).lower() or "mask" in rel.group(1).lower():
            continue
        sizes = [int(x) for x in re.findall(r"(\d+)x\d+", tag)]
        score = max(sizes) if sizes else 0
        if "apple-touch" in rel.group(1).lower():
            score = max(score, 180)
        if href.group(1).lower().endswith(".ico"):
            score -= 100                             # .ico: di solito piccole
        cands.append((score, urllib.parse.urljoin(base, href.group(1).replace("&amp;", "&"))))
    cands.sort(reverse=True)
    return [u for _, u in cands] + [urllib.parse.urljoin(base, "/apple-touch-icon.png"),
                                    urllib.parse.urljoin(base, "/favicon.ico")]


def site_icon(url):
    """(dati, tipo) del logo del sito, oppure None."""
    p = urlparse(url or "")
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    base = f"{p.scheme}://{p.hostname}/"
    os.makedirs(ICON_DIR, exist_ok=True)
    path = os.path.join(ICON_DIR, re.sub(r"[^a-z0-9.-]", "_", p.hostname.lower()))
    with icon_lock:
        for ext, ctype in (("img", None), ("none", None)):
            f = path + "." + ext
            if os.path.exists(f) and time.time() - os.path.getmtime(f) < 30 * 86400:
                if ext == "none":
                    return None                      # già cercato senza successo
                with open(f, "rb") as fh:
                    data = fh.read()
                with open(path + ".type") as fh:
                    return data, fh.read().strip()
        try:
            cands = _icon_candidates(base)
        except Exception as ex:
            log.info("logo di %s: pagina non letta (%s)", p.hostname, ex)
            cands = [urllib.parse.urljoin(base, "/apple-touch-icon.png"), urllib.parse.urljoin(base, "/favicon.ico")]
        for u in cands[:6]:
            try:
                data, ctype = _fetch(u)
            except Exception:
                continue
            if ctype.startswith("image/") and len(data) > 200:
                with open(path + ".img", "wb") as fh:
                    fh.write(data)
                with open(path + ".type", "w") as fh:
                    fh.write(ctype)
                return data, ctype
        open(path + ".none", "w").close()
        return None


# --------------------------------------------------------------------------
# HTTP: launcher + API
# --------------------------------------------------------------------------
def make_handler(tv):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=LAUNCHER_DIR, **kw)

        def log_message(self, *a):
            pass

        def end_headers(self):
            # il launcher cambia con gli aggiornamenti: Chrome deve sempre ricontrollarlo
            if not self.path.startswith("/api/"):
                self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if not u.path.startswith("/api/"):
                return super().do_GET()
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            ep = u.path[5:]
            if ep == "config":
                c = tv.cfg
                return self._json({"sections": c["sections"], "services": c["services"],
                                   "other_services": c.get("other_services", []),
                                   "hidden": home_load()["hidden"],
                                   "my_sites": [x for x in sites_load() if x.get("home")]})
            if ep == "home":
                return self._json(home_api(q))
            if ep == "onair":
                return self._json(onair(tv.services))
            if ep == "meteo":
                return self._json(meteo_api(q))
            if ep == "icon":
                r = site_icon(q.get("url", ""))
                if not r:
                    return self._json({"error": "nessun logo"}, 404)
                data, ctype = r
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(data)
                return
            if ep == "open":
                tv.post(tv.open, q.get("id", ""))
                return self._json({"ok": True})
            if ep == "openurl":
                u = normalize_url(q.get("url"))
                if not u:
                    return self._json({"ok": False, "error": "Indirizzo non valido"})
                tv.post(tv.open_url, u)
                return self._json({"ok": True, "url": u})
            if ep == "sites":
                return self._json(sites_api(q))
            if ep == "volume":
                return self._json({"volume": tv.volume(int(q.get("delta", "0")))})
            if ep == "info":
                ip = subprocess.run(["hostname", "-I"], capture_output=True,
                                    text=True).stdout.split()
                return self._json({"hostname": socket.gethostname(), "ip": ip,
                                   "remote_aluminium": tv_remote.aluminium if tv_remote else None})
            if ep == "wifi":
                a = q.get("action", "status")
                if a == "scan":
                    return self._json(wifi_scan())
                if a == "connect":
                    return self._json(wifi_connect(q.get("ssid", ""), q.get("password", "")))
                if a == "forget":
                    return self._json(wifi_forget(q.get("ssid", "")))
                return self._json(wifi_status())
            if ep == "screen":
                a = q.get("action", "status")
                if a == "try":
                    mode = q.get("mode", "")
                    if mode != "auto" and mode not in tv.screen_info()["modes"]:
                        return self._json({"ok": False, "error": "Risoluzione non disponibile"})
                    tv.post(tv.screen_try, mode)
                    return self._json({"ok": True, "seconds": 15})
                if a == "video":
                    tv.post(tv.screen_video, q.get("on") == "1")
                    return self._json({"ok": True})
                if a == "keep":
                    tv.post(tv.screen_keep)
                    return self._json({"ok": True})
                if a == "revert":
                    tv.post(tv.screen_revert)
                    return self._json({"ok": True})
                return self._json(tv.screen_info())
            if ep == "system":
                a = q.get("action")
                if a == "restart-ui":
                    threading.Thread(target=lambda: (time.sleep(0.5), tv.browser.kill()),
                                     daemon=True).start()
                elif a in ("reboot", "poweroff"):
                    subprocess.Popen(["sudo", "-n", "/usr/bin/systemctl", a])
                return self._json({"ok": True})
            return self._json({"error": "not found"}, 404)
    return Handler


tv_remote = None


def main():
    global tv_remote
    logging.basicConfig(level=logging.INFO, format="%(asctime)s tvd %(levelname)s %(message)s")
    cfg = load_config()
    tv = TV(cfg)
    srv = ThreadingHTTPServer(("127.0.0.1", cfg.get("http_port", 8765)), make_handler(tv))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=tv.worker, daemon=True).start()
    tv_remote = Remote(tv)
    tv_remote.start()

    def bye(*_):
        log.info("uscita")
        tv.browser.kill()
        os._exit(0)
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)

    if cfg.get("video_mode") or full_mode() != "auto":
        try:
            xr_set(full_mode())              # si parte dalla risoluzione scelta (o da quella piena)
        except Exception as ex:
            log.warning("xrandr: %s", ex)
    tv.browser.kill_stale()
    tv.watchdog()


if __name__ == "__main__":
    main()

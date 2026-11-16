"""Avvio di Google Chrome in modalità kiosk e script iniettati nelle pagine."""
import functools
import json
import os
import signal
import subprocess
import time

from .util import LAUNCHER_DIR, log, read_text

INJECT_DIR = os.path.join(LAUNCHER_DIR, "inject")


def inject_scripts(force_h264=True):
    """Script registrati in ogni pagina, dal più importante al più pesante:
    helper (player, schermo intero) · h264 · tastiera a schermo · navigazione assistita ·
    protezione da popup e pubblicità · simulatore HbbTV con hls.js (attivo solo se Chrome
    si presenta come televisore HbbTV)."""
    names = ["helper.js"] + (["h264.js"] if force_h264 else []) + ["osk.js", "nav.js", "shield.js"]
    out = [js for js in (read_text(os.path.join(INJECT_DIR, n)) for n in names) if js]
    hls = read_text(os.path.join(LAUNCHER_DIR, "vendor", "hls.min.js"))
    hbb = read_text(os.path.join(INJECT_DIR, "hbbtv.js"))
    if hls and hbb:
        out.append("(function(){if(!/HbbTV\\//.test(navigator.userAgent))return;\n"
                   + hls + "\n;\n" + hbb + "\n}).call(window);")
    return out


@functools.lru_cache(maxsize=1)
def layer_script():
    """Lo strato TV (inject/layer.js) con le schede e lo stile della home (js/cards.js,
    css/tokens.css, css/cards.css). Letto una volta: cambia solo con un aggiornamento."""
    parts = [read_text(os.path.join(LAUNCHER_DIR, f)) for f in
             ("js/cards.js", "css/tokens.css", "css/cards.css", "inject/layer.js")]
    if not all(parts):
        log.error("strato TV: file mancanti")
        return ""
    cards_js, tokens, cards_css, js = parts
    return cards_js + "\n;window.__tvCardsCSS = " + json.dumps(tokens + "\n" + cards_css) + ";\n" + js


class Browser:
    def __init__(self, cfg, start_url, scale_factor=lambda: 1.0):
        self.cfg = cfg
        self.start_url = start_url
        self.scale_factor = scale_factor
        self.profile = os.path.expanduser(cfg.opt("chrome.profile_dir", "~/.config/tvbox-chrome"))
        self.proc = None
        self.started_at = 0.0
        self.dsf = 1.0

    def _mark_clean_exit(self):
        """Evita il fumetto "Chrome non si è chiuso correttamente" dopo un crash."""
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

    def wanted_dsf(self):
        v = self.cfg.opt("chrome.device_scale_factor", "auto")
        return self.scale_factor() if v == "auto" else float(v)

    def start(self):
        os.makedirs(self.profile, exist_ok=True)
        self._mark_clean_exit()
        args = [
            self.cfg.opt("chrome.binary", "google-chrome-stable"),
            f"--user-data-dir={self.profile}",
            "--kiosk", "--start-fullscreen", "--window-position=0,0",
            "--no-first-run", "--no-default-browser-check", "--noerrdialogs",
            "--disable-session-crashed-bubble", "--disable-infobars",
            "--password-store=basic",
            "--autoplay-policy=no-user-gesture-required",
            "--enable-spatial-navigation",
            "--overscroll-history-navigation=0", "--disable-pinch",
            "--disable-features=Translate,TranslateUI,MediaRouter,GlobalMediaControls",
            f"--remote-debugging-port={self.cfg.opt('chrome.cdp_port', 9222)}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
        ]
        if self.cfg.opt("chrome.disable_gpu", False):
            args.append("--disable-gpu")
        self.dsf = self.wanted_dsf()
        if abs(self.dsf - 1.0) > 0.01:
            args.append(f"--force-device-scale-factor={self.dsf}")
        args.append(self.start_url)
        logf = open(os.path.join(self.profile, "tvbox-chrome.log"), "ab")
        self.proc = subprocess.Popen(args, stdout=logf, stderr=logf, start_new_session=True)
        self.started_at = time.monotonic()
        log.info("Chrome avviato (pid %s, ingrandimento %.2f)", self.proc.pid, self.dsf)

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

"""API HTTP su 127.0.0.1 per il launcher, e i file del launcher stesso.

Ogni indirizzo /api/<nome> corrisponde a una funzione (tabella ROUTES): riceve i parametri
della richiesta (dizionario) e restituisce un oggetto JSON. Stesse risposte della V1.
"""
import json
import socket
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import wifi
from .meteo import Meteo
from .sites import normalize_url, site_icon
from .util import LAUNCHER_DIR


class Binary:
    """Risposta non JSON (immagini)."""

    def __init__(self, data, ctype, max_age=86400):
        self.data, self.ctype, self.max_age = data, ctype, max_age


def make_routes(tv):
    meteo = Meteo(tv.prefs)

    def config(q):
        return dict(tv.cfg.ui(), hidden=tv.prefs.get("hidden"),
                    my_sites=[x for x in tv.sites.list() if x.get("home")])

    def home(q):
        """Riquadri nascosti dalla home o da Altri servizi."""
        sid, a = q.get("id", ""), q.get("action")
        if sid and sid != "impostazioni" and a in ("hide", "show"):
            tv.prefs.update("hidden", lambda h: [x for x in h if x != sid] + ([sid] if a == "hide" else []))
        return {"hidden": tv.prefs.get("hidden")}

    def icon(q):
        r = site_icon(q.get("url", ""))
        return Binary(*r) if r else ({"error": "nessun logo"}, 404)

    def open_(q):
        tv.post(tv.open, q.get("id", ""))
        return {"ok": True}

    def openurl(q):
        u = normalize_url(q.get("url"))
        if not u:
            return {"ok": False, "error": "Indirizzo non valido"}
        tv.post(tv.open_url, u)
        return {"ok": True, "url": u}

    def info(q):
        ip = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()
        return {"hostname": socket.gethostname(), "ip": ip,
                "remote_aluminium": tv.remote.aluminium if tv.remote else None}

    def wifi_(q):
        a = q.get("action", "status")
        if a == "scan":
            return wifi.wifi_scan()
        if a == "connect":
            return wifi.wifi_connect(q.get("ssid", ""), q.get("password", ""))
        if a == "forget":
            return wifi.wifi_forget(q.get("ssid", ""))
        return wifi.wifi_status()

    def screen(q):
        a, d = q.get("action", "status"), tv.display
        if a == "try":
            mode = q.get("mode", "")
            if mode != "auto" and mode not in d.info()["modes"]:
                return {"ok": False, "error": "Risoluzione non disponibile"}
            tv.post(d.try_mode, mode)
            return {"ok": True, "seconds": 15}
        if a == "video":
            tv.post(d.set_video_low, q.get("on") == "1")
        elif a == "keep":
            tv.post(tv.screen_keep)
        elif a == "revert":
            tv.post(d.revert)
        else:
            return d.info()
        return {"ok": True}

    def system(q):
        a = q.get("action")
        if a == "restart-ui":
            threading.Thread(target=lambda: (time.sleep(0.5), tv.browser.kill()), daemon=True).start()
        elif a in ("reboot", "poweroff"):
            subprocess.Popen(["sudo", "-n", "/usr/bin/systemctl", a])
        return {"ok": True}

    return {
        "config": config, "home": home, "icon": icon, "open": open_, "openurl": openurl,
        "onair": lambda q: tv.epg.onair(), "meteo": meteo.api, "sites": tv.sites.api,
        "volume": lambda q: {"volume": tv.volume(int(q.get("delta", "0") or 0))},
        "info": info, "wifi": wifi_, "screen": screen, "system": system,
    }


def make_handler(routes):
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

        def _send(self, body, ctype, code=200, cache="no-store"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", cache)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if not u.path.startswith("/api/"):
                return super().do_GET()
            fn = routes.get(u.path[5:])
            if not fn:
                return self._send(b'{"error": "not found"}', "application/json", 404)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            res, code = fn(q), 200
            if isinstance(res, tuple):
                res, code = res
            if isinstance(res, Binary):
                return self._send(res.data, res.ctype, cache=f"max-age={res.max_age}")
            self._send(json.dumps(res).encode(), "application/json", code)
    return Handler


def serve(tv, port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(make_routes(tv)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

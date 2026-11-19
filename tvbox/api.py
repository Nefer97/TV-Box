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
        return dict(tv.cfg.ui(tv.prefs.get("channels")), hidden=tv.prefs.get("hidden"),
                    pinned=[x for x in tv.prefs.get("pinned") if x in tv.cfg.other],
                    my_sites=[x for x in tv.sites.list() if x.get("home")])

    def home(q):
        """Riquadri nascosti dalla home o da Altri servizi (i canali si scelgono con channels);
        pin / unpin: un servizio di Altri servizi anche (o non più) tra i riquadri grandi della home."""
        sid, a = q.get("id", ""), q.get("action")
        if sid and sid != "impostazioni" and sid not in tv.cfg.channels and a in ("hide", "show"):
            tv.prefs.update("hidden", lambda h: [x for x in h if x != sid] + ([sid] if a == "hide" else []))
        if sid in tv.cfg.other and a in ("pin", "unpin"):
            tv.prefs.update("pinned", lambda p: [x for x in p if x != sid] + ([sid] if a == "pin" else []))
            if a == "pin":                               # in home vuol dire anche visibile
                tv.prefs.update("hidden", lambda h: [x for x in h if x != sid])
        return {"hidden": tv.prefs.get("hidden"), "pinned": tv.prefs.get("pinned")}

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

    def guide(q):
        """Guida TV: canali in diretta e, per quello chiesto, i programmi delle prossime ore."""
        chans = [{"id": sid, "label": tv.services[sid]["label"], "color": tv.services[sid].get("color")}
                 for sid in tv.channel_list()]
        sid = q.get("id") or (chans[0]["id"] if chans else "")
        return {"channels": chans, "id": sid, "programs": tv.epg.guide(sid, hours=int(q.get("hours", 12)))
                if sid in tv.services else []}

    def prefs(q):
        """Scelte semplici dalla TV (per ora: cosa fare all'accensione)."""
        k, v = q.get("key"), q.get("value")
        if k == "startup" and v in ("last", "home"):
            tv.prefs.set("startup", v)
        elif k == "saver_off" and (v or "").isdigit():
            tv.prefs.set("saver_off", int(v))
        return {"startup": tv.prefs.get("startup"), "saver_off": tv.prefs.get("saver_off")}

    def sleep(q):
        if "minutes" in q:
            try:
                return tv.sleep_set(max(0, min(240, int(q["minutes"]))))
            except ValueError:
                pass
        return {"minutes": tv.sleep_left()}

    def discovery(q):
        """discovery+: accesso all'account (login con email e password fatto da tvd; logout;
        status; site = accesso sul sito, se discovery+ chiede la verifica anti-robot). Il
        riquadro di discovery+ apre il sito: lì l'account è già collegato."""
        a = q.get("action", "status")
        if a == "login":
            return tv.discovery.login(q.get("user", ""), q.get("password", ""))
        if a == "logout":
            return dict(tv.discovery.logout(), ok=True)
        if a == "site":
            tv.post(tv.open_login, "discovery")
            return {"ok": True}
        return tv.discovery.login_state()

    def mediaset(q):
        """Sezione Mediaset: righe di serie, una serie con i suoi episodi, apertura di un episodio,
        accesso (login con email e password; logout; status; site = accesso sul sito, se Mediaset
        chiede il captcha)."""
        from .mediaset import is_episode_url
        a = q.get("action", "rails")
        if a == "status":
            return tv.mediaset.login_state()
        if a == "login":
            return tv.mediaset.login(q.get("user", ""), q.get("password", ""))
        if a == "logout":
            return dict(tv.mediaset.logout(), ok=True)
        if a == "site":
            tv.post(tv.open_login, "mediaset")
            return {"ok": True}
        if a == "series":
            return tv.mediaset.series(q.get("id", ""), q.get("season"))
        if a == "play":
            if not is_episode_url(q.get("url")):
                return {"ok": False, "error": "Episodio non valido"}
            tv.mediaset.remember(q)
            label = " · ".join(x for x in (q.get("title"), q.get("ep")) if x)
            tv.post(tv.open_episode, q["url"], q.get("series", ""), label)
            return {"ok": True}
        return tv.mediaset.rails()

    def sc(q):
        """StreamingCommunity (tvbox/sc.py): righe, una serie con i suoi episodi, apertura di un
        episodio, accesso al sito (login con utente e password; logout; status)."""
        from .sc import is_episode_url
        a = q.get("action", "rails")
        if a == "search":
            return tv.sc.search(q.get("q", ""))
        if a == "series":
            return tv.sc.series(q.get("id", ""), q.get("season"))
        if a == "play":
            if not is_episode_url(q.get("url")):
                return {"ok": False, "error": "Episodio non valido"}
            tv.sc.remember(q)
            label = " · ".join(x for x in (q.get("title"), q.get("ep")) if x)
            site = tv.services.get("sc", {}).get("label", "StreamingCommunity")
            target, referrer = tv.sc.play_target(q["url"])     # il player da solo, a tutto schermo
            tv.post(lambda: tv.open_episode(target, q.get("series", ""), label, site=site, back="sc",
                                            color="#9d174d", referrer=referrer, key=q["url"]))
            return {"ok": True}
        if a == "login":                       # utente e password dalla schermata di tvbox
            return tv.sc.login(q.get("user", ""), q.get("password", ""))
        if a == "logout":
            return dict(tv.sc.logout(), ok=True)
        if a == "status":
            return tv.sc.login_state(fresh=q.get("fresh") == "1")
        return tv.sc.rails(q.get("page"))

    def au(q):
        """AnimeUnity (tvbox/au.py): righe, un anime con i suoi episodi, ricerca, apertura di un
        episodio, accesso al sito (login con utente e password; logout; status)."""
        from .au import is_episode_url
        a = q.get("action", "rails")
        if a == "search":
            return tv.au.search(q.get("q", ""))
        if a == "series":
            return tv.au.series(q.get("id", ""), q.get("season"))
        if a == "play":
            if not is_episode_url(q.get("url")):
                return {"ok": False, "error": "Episodio non valido"}
            tv.au.remember(q)
            label = " · ".join(x for x in (q.get("title"), q.get("ep")) if x)
            site = tv.services.get("au", {}).get("label", "AnimeUnity")
            target, referrer = tv.au.play_target(q["url"])     # il player da solo, a tutto schermo
            tv.post(lambda: tv.open_episode(target, q.get("series", ""), label, site=site, back="au",
                                            color="#1e3a8a", referrer=referrer, key=q["url"]))
            return {"ok": True}
        if a == "login":                       # utente e password dalla schermata di tvbox
            return tv.au.login(q.get("user", ""), q.get("password", ""))
        if a == "logout":
            return dict(tv.au.logout(), ok=True)
        if a == "status":
            return tv.au.login_state(fresh=q.get("fresh") == "1")
        return tv.au.rails(q.get("page"))

    def channels(q):
        """Catalogo dei canali: quali sono nella home e in che ordine (Impostazioni → Canali)."""
        from .channels import GROUPS, clean_selection
        cat = tv.cfg.channels
        sel = clean_selection(tv.prefs.get("channels"), cat)
        cid, a = q.get("id", ""), q.get("action")
        if cid in cat and a in ("add", "remove", "up", "down"):
            if a == "add" and cid not in sel:
                sel.append(cid)
            elif a == "remove" and cid in sel and len(sel) > 1:
                sel.remove(cid)
            elif a in ("up", "down") and cid in sel:
                i = sel.index(cid)
                j = i - 1 if a == "up" else i + 1
                if 0 <= j < len(sel):
                    sel[i], sel[j] = sel[j], sel[i]
            sel = tv.prefs.set("channels", sel)
        groups = [{"id": g, "title": t, "items": [{"id": c, "label": s["label"], "on": c in sel,
                                                  "pos": sel.index(c) + 1 if c in sel else None,
                                                  "guide": bool(s.get("onair"))}
                                                 for c, s in cat.items() if s.get("group") == g]}
                  for g, t in GROUPS]
        return {"selected": sel, "groups": groups}

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
        # dove si è arrivati negli episodi: {"<url>": {"t": secondi, "d": durata}}
        "progress": lambda q: {u: {"t": v[0], "d": v[1]} for u, v in (tv.prefs.get("progress") or {}).items()},
        "info": info, "wifi": wifi_, "screen": screen, "system": system,
        "guide": guide, "prefs": prefs, "sleep": sleep, "mediaset": mediaset, "discovery": discovery, "sc": sc, "au": au, "channels": channels,
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

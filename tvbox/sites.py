"""I miei siti: indirizzi scelti dall'utente (nelle preferenze) e i loro loghi.

I loghi sono l'icona "app" che il sito stesso pubblica (apple-touch-icon o simili),
scaricata una volta e conservata in ~/.config/tvbox/icons per 30 giorni.
"""
import os
import re
import threading
import time
import urllib.parse
from urllib.parse import urlparse

from .util import USER_DIR, fetch, log

ICON_DIR = os.path.join(USER_DIR, "icons")
icon_lock = threading.Lock()


def normalize_url(u):
    """Indirizzo completo (https:// aggiunto se manca) oppure None se non è valido."""
    u = (u or "").strip()
    if not u:
        return None
    if not re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I):
        u = "https://" + u
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname:
        return None
    return u


class Sites:
    def __init__(self, prefs):
        self.prefs = prefs

    def list(self):
        return self.prefs.get("sites")

    def find(self, url):
        return next((x for x in self.list() if x["url"] == url), None)

    def api(self, q):
        a = q.get("action", "list")
        url = q.get("url")
        if a == "add":
            u = normalize_url(url)
            if not u:
                return {"ok": False, "error": "Indirizzo non valido"}
            label = (q.get("label") or urlparse(u).hostname or u).strip()[:40]
            self.prefs.update("sites", lambda l: [x for x in l if x["url"] != u] + [{"label": label, "url": u}])
        elif a == "remove":
            self.prefs.update("sites", lambda l: [x for x in l if x["url"] != url])
        elif a in ("mobile", "home"):          # vista telefono · metti/togli dalla home
            on = q.get("on") == "1"
            self.prefs.update("sites", lambda l: [dict(x, **{a: on}) if x["url"] == url else x for x in l])
        return {"ok": True, "sites": self.list()}


def _icon_candidates(base):
    """Icone dichiarate dalla pagina, dalla migliore: apple-touch-icon e dimensioni grandi."""
    html, _ = fetch(base, limit=400_000)
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
    return [u for _, u in cands] + _fallback(base)


def _fallback(base):
    return [urllib.parse.urljoin(base, "/apple-touch-icon.png"), urllib.parse.urljoin(base, "/favicon.ico")]


def site_icon(url):
    """(dati, tipo) del logo del sito, oppure None."""
    p = urlparse(url or "")
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    base = f"{p.scheme}://{p.hostname}/"
    os.makedirs(ICON_DIR, exist_ok=True)
    path = os.path.join(ICON_DIR, re.sub(r"[^a-z0-9.-]", "_", p.hostname.lower()))
    fresh = lambda f: os.path.exists(f) and time.time() - os.path.getmtime(f) < 30 * 86400  # noqa: E731
    with icon_lock:
        if fresh(path + ".img"):
            with open(path + ".img", "rb") as fh, open(path + ".type") as ft:
                return fh.read(), ft.read().strip()
        if fresh(path + ".none"):
            return None                          # già cercato senza successo
        try:
            cands = _icon_candidates(base)
        except Exception as ex:
            log.info("logo di %s: pagina non letta (%s)", p.hostname, ex)
            cands = _fallback(base)
        for u in cands[:6]:
            try:
                data, ctype = fetch(u)
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

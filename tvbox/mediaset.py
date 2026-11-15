"""Catalogo Mediaset Infinity (fiction e serie) per la sezione Mediaset della TV.

I dati vengono dai feed pubblici usati anche dal sito (nessun account):
    serie     .../mediaset-prod-all-series-v2     categoria, locandine, stagioni, pagina
    episodi   .../mediaset-prod-all-programs-v2   per stagione: numero, titolo, durata, video

Il video si guarda sulla pagina dell'episodio del sito (con il suo player e la licenza),
aperta da tvd a tutto schermo. La TV ricorda gli ultimi episodi aperti ("Continua a guardare").
Le funzioni parse_* lavorano sui dati già scaricati: si provano con i test.
"""
import threading
import time
import urllib.parse

from .util import get_json, log

FEED = "https://feed.entertainment.tv.theplatform.eu/f/PR1GhC/"
SERIES_FIELDS = ("guid,title,description,thumbnails,seriesTvSeasons,tags,updated,"
                 "mediasetprogram$pageUrl,mediasetprogram$currentSeason")

# righe della sezione: (id, titolo, categoria nel catalogo Mediaset)
RAILS = [("fiction", "Fiction e soap in onda", "Fiction"), ("serie", "Serie TV", "Serie TV")]
HISTORY_MAX = 12


def _img(thumbs, *keys):
    for k in keys:
        v = (thumbs or {}).get(k)
        if v and v.get("url"):
            return v["url"]
    return ""


def _https(u):
    return ("https:" + u) if u and u.startswith("//") else (u or "")


def parse_series(e):
    th = e.get("thumbnails") or {}
    seasons = sorted(({"id": s.get("id"), "guid": s.get("guid"), "n": s.get("tvSeasonNumber") or 0,
                       "year": s.get("startYear"), "title": s.get("title") or ""}
                      for s in e.get("seriesTvSeasons") or [] if s.get("id")), key=lambda s: s["n"])
    cats = [t.get("title") for t in e.get("tags") or [] if t.get("scheme") == "category"]
    return {"id": e.get("guid"), "title": e.get("title") or "", "desc": e.get("description") or "",
            "poster": _img(th, "image_vertical-264x396", "image_vertical-192x288", "img_s_master_boxart-1080x1440"),
            "hero": _img(th, "img_s_master_16_9-1920x1080", "image_keyframe_poster-1280x720",
                         "image_header_poster-1440x630"),
            "seasons": seasons, "current": ((e.get("mediasetprogram$currentSeason") or {}).get("default")),
            "category": cats[0] if cats else "", "url": _https(e.get("mediasetprogram$pageUrl"))}


def parse_episode(e):
    th = e.get("thumbnails") or {}
    pub = (e.get("mediasetprogram$publishInfo") or {})
    date = 0
    if pub.get("last_published"):
        try:
            import calendar
            date = calendar.timegm(time.strptime(pub["last_published"][:19], "%Y-%m-%dT%H:%M:%S")) * 1000
        except ValueError:
            pass
    return {"id": e.get("guid"), "n": e.get("tvSeasonEpisodeNumber"), "season": e.get("tvSeasonNumber"),
            "title": e.get("title") or "", "desc": e.get("description") or "",
            "dur": int(e.get("mediasetprogram$duration") or 0), "date": date,
            "channel": pub.get("description") or "",
            "image": _img(th, "image_keyframe_poster-360x203", "image_keyframe_poster-391x220",
                          "image_keyframe_poster-292x165"),
            "url": _https(e.get("mediasetprogram$videoPageUrl")),
            "free": "AVOD" in (e.get("mediasetprogram$channelsRights") or [])}


def episodes_of(entries):
    """Solo episodi veri (con numero) e gratuiti, dal più recente."""
    eps = [parse_episode(e) for e in entries]
    eps = [x for x in eps if x["n"] is not None and x["url"] and x["free"]]
    return sorted(eps, key=lambda x: (x["n"], x["date"]), reverse=True)   # numeri doppi: conta la data


def is_episode_url(u):
    p = urllib.parse.urlparse(u or "")
    return p.scheme == "https" and p.hostname == "mediasetinfinity.mediaset.it" and p.path.startswith("/video/")


class Mediaset:
    def __init__(self, prefs):
        self.prefs = prefs
        self.lock = threading.Lock()
        self.cache = {}                     # chiave -> (istante, dati)

    def _get(self, key, url, ttl):
        with self.lock:
            c = self.cache.get(key)
            if c and time.monotonic() - c[0] < ttl:
                return c[1]
        try:
            d = get_json(url, timeout=12)
        except Exception as ex:
            log.warning("Mediaset %s non disponibile: %s", key, ex)
            return c[1] if c else {}
        with self.lock:
            self.cache[key] = (time.monotonic(), d)
        return d

    # ---------- righe della sezione ----------
    def rails(self):
        out = []
        hist = self.history()
        if hist:
            out.append({"id": "continua", "title": "Continua a guardare", "items": hist})
        for rid, title, cat in RAILS:
            url = (FEED + "mediaset-prod-all-series-v2?byTags=" + urllib.parse.quote("category:" + cat) +
                   "&sort=updated%7Cdesc&range=1-30&fields=" + urllib.parse.quote(SERIES_FIELDS, safe=","))
            items = [parse_series(e) for e in self._get("rail:" + rid, url, 1800).get("entries") or []]
            out.append({"id": rid, "title": title, "items": [x for x in items if x["poster"] and x["seasons"]]})
        return {"rails": out}

    # ---------- una serie: stagioni ed episodi ----------
    def series(self, guid, season=None):
        url = (FEED + "mediaset-prod-all-series-v2?byGuid=" + urllib.parse.quote(guid) +
               "&fields=" + urllib.parse.quote(SERIES_FIELDS, safe=","))
        ents = self._get("serie:" + guid, url, 1800).get("entries") or []
        if not ents:
            return {"error": "Serie non trovata"}
        s = parse_series(ents[0])
        if not s["seasons"]:
            return dict(s, episodes=[], season=None)
        pick = next((x for x in s["seasons"] if x["guid"] == season or x["id"] == season), None) \
            or next((x for x in s["seasons"] if x["guid"] == s["current"]), None) or s["seasons"][-1]
        url = (FEED + "mediaset-prod-all-programs-v2?byTvSeasonId=" + urllib.parse.quote(pick["id"], safe="") +
               "&sort=tvSeasonEpisodeNumber%7Cdesc&range=1-120")
        eps = episodes_of(self._get("eps:" + pick["id"], url, 900).get("entries") or [])
        last = next((h for h in self.prefs.get("ms_history") if h["series"] == guid), None)
        return dict(s, season=pick["guid"], episodes=eps, last=last["episode"] if last else None)

    # ---------- Continua a guardare ----------
    def history(self):
        return [{"id": h["series"], "title": h["title"], "poster": h["poster"],
                 "sub": f"Ep. {h['n']}" if h.get("n") is not None else "", "episode": h["episode"]}
                for h in self.prefs.get("ms_history")]

    def remember(self, q):
        """Ricorda l'episodio aperto (in cima a "Continua a guardare", una voce per serie)."""
        h = {"series": q.get("series", ""), "title": (q.get("title") or "")[:60],
             "poster": q.get("poster", ""), "episode": q.get("episode", ""),
             "n": int(q["n"]) if (q.get("n") or "").isdigit() else None, "t": int(time.time())}
        if not h["series"]:
            return
        self.prefs.update("ms_history", lambda l: ([h] + [x for x in l if x["series"] != h["series"]])[:HISTORY_MAX])

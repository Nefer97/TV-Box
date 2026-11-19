"""AnimeUnity: catalogo di anime per la sezione AnimeUnity della TV (id "au").

Il file ha due parti:

  1. IL CONNETTORE (da scrivere): poche funzioni che sanno parlare con il sito: le righe della
     HOME e della scheda ANIME, la ricerca, un anime con i suoi episodi, l'accesso. Restituiscono
     dizionari nel formato qui sotto (usa serie() ed episodio() per non dimenticare campi).
  2. LA CLASSE AU (già pronta): cache, "Continua a guardare", stato dell'accesso, cookie in
     Chrome e risposte al launcher (launcher/js/au.js). Non serve toccarla.

Finché una funzione del connettore alza NotImplementedError, la TV mostra "connettore non
ancora scritto" al posto dei dati: si può lavorare un pezzo alla volta e provare sul PC con
  python3 tools/uitest/server.py 8811     e il browser su  http://127.0.0.1:8811/#au

Modello: tvbox/sc.py (StreamingCommunity) fa le stesse cose per un altro sito.

FORMATO DEI DATI
  serie     {"id", "title", "poster", "hero", "logo", "desc", "category", "genres": [...],
             "seasons": [{"id", "n", "title"}], "current": id della stagione di partenza}
            id: stringa che il connettore sa ritrovare (es. "1234-one-piece").
            poster: locandina verticale; hero: immagine larga di sfondo; logo: facoltativo.
            seasons: almeno una (un anime senza stagioni = una sola "Episodi").
  episodio  {"id", "url", "title", "n", "desc", "dur", "date", "channel", "image"}
            url: la pagina dell'episodio sul sito, che tvbox apre a schermo intero (deve
            passare is_episode_url); n: numero (o None); dur: secondi; date: millisecondi.
  riga      {"id", "title", "items": [serie, ...]}
"""
import html
import http.cookiejar
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .util import DESKTOP_UA, log

NAME = "au"

# ======================================================================================
# 1. IL CONNETTORE — da scrivere
# ======================================================================================

SITE_HOST = "animeunity.cx"
BASE_URL = f"https://{SITE_HOST}"
EPISODE_PATH = "/anime/"

LOGIN_REQUIRED = False
SESSION_COOKIES = ()
LOGIN_STATUS_TTL = 300

RAIL_TTL = 1800
SERIES_TTL = 900
DETAILS_TTL = 24 * 3600            # descrizione di un titolo evidenziato: un giorno
EP_GROUP = 100                     # serie lunghissime senza stagioni (One Piece): episodi a gruppi di 100
HISTORY_MAX = 12


def _d(value):
    return value if isinstance(value, dict) else {}


def _l(value):
    return value if isinstance(value, list) else []


def _s(value):
    return str(value).strip() if value is not None else ""


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _api(path, params=None):
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, headers={
        "User-Agent": DESKTOP_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        "Referer": BASE_URL + "/",
        "X-Requested-With": "XMLHttpRequest",
    })

    with urllib.request.urlopen(req, timeout=20) as response:
        return __import__("json").loads(
            response.read().decode("utf-8", "replace")
        )


def _page(path):
    """Dati di una pagina del sito (Laravel + Inertia, come StreamingCommunity): le "props" che
    la pagina porta con sé nell'attributo data-page (anime, embedUrl, ...)."""
    req = urllib.request.Request(BASE_URL + path, headers={
        "User-Agent": DESKTOP_UA, "Accept": "text/html", "Accept-Language": "it-IT,it;q=0.9",
        "Referer": BASE_URL + "/"})
    with urllib.request.urlopen(req, timeout=20) as response:
        text = response.read().decode("utf-8", "replace")
    m = re.search(r'data-page="([^"]*)"', text)
    if not m:
        raise ValueError(f"pagina senza dati: {path}")
    return _d(json.loads(html.unescape(m.group(1))).get("props"))


def _sid(anime):
    anime = _d(anime)
    return f"{anime.get('id')}-{anime.get('slug')}"


def _images(anime):
    return _d(_d(anime).get("images"))


def serie(id, title, poster="", hero="", logo="", desc="",
          category="Anime", genres=None, seasons=None, current=None):
    if seasons is None:
        seasons = [("1", 1, "Episodi")]

    return {
        "id": str(id),
        "title": title or "",
        "poster": poster or "",
        "hero": hero or poster or "",
        "logo": logo or "",
        "desc": desc or "",
        "category": category,
        "genres": list(genres or [])[:3],
        "seasons": [
            {"id": str(s[0]), "n": int(s[1]), "title": str(s[2])}
            for s in seasons
        ],
        "current": current,
    }


def episodio(id, url, title="", n=None, desc="", dur=0,
             date=0, image=""):
    return {
        "id": str(id),
        "url": url,
        "title": title or (f"Episodio {n}" if n is not None else "Episodio"),
        "n": n,
        "desc": desc or "",
        "dur": int(dur or 0),
        "date": int(date or 0),
        "channel": "",
        "image": image or "",
    }


def _parse_series(anime):
    anime = _d(anime)
    images = _images(anime)

    genres = [
        _s(g.get("name"))
        for g in _l(anime.get("genres"))
        if isinstance(g, dict) and _s(g.get("name"))
    ]

    s = serie(
        id=_sid(anime),
        title=anime.get("title_it") or anime.get("title"),
        poster=images.get("poster") or images.get("cover") or "",
        hero=images.get("banner") or images.get("cover") or "",
        logo=images.get("logo") or "",
        desc=anime.get("plot") or "",
        genres=genres,
    )
    s["adult"] = bool(anime.get("is_adult"))     # per adulti (se il sito lo dice; vedi AU._visible)
    return s


def _parse_episode(raw, anime_sid, poster=""):
    raw = _d(raw)
    videos = [
        v for v in _l(raw.get("videos"))
        if isinstance(v, dict) and not v.get("is_hidden")
    ]

    if not videos:
        return None

    # Preferenza: italiano, giapponese, cinese, coreano, inglese.
    priorities = ("ita", "jpn", "chn", "kor", "eng")
    video = next(
        (v for lang in priorities for v in videos
         if _s(v.get("language")).lower() == lang),
        videos[0],
    )

    video_id = _s(video.get("id"))
    if not video_id:
        return None

    number_raw = raw.get("number")
    number = _int(number_raw, None)

    url = f"{BASE_URL}{EPISODE_PATH}{anime_sid}/{video_id}"

    return episodio(
        id=video_id,
        url=url,
        title=f"Episodio {number}" if number is not None else "Episodio",
        n=number,
        dur=video.get("runtime") or 0,
        image=poster,
    )


def is_episode_url(u):
    p = urllib.parse.urlparse(u or "")
    parts = p.path.strip("/").split("/")

    return (
        p.scheme == "https"
        and p.hostname == SITE_HOST
        and len(parts) == 3
        and parts[0] == "anime"
        and parts[1].split("-", 1)[0].isdigit()
        and parts[2].isdigit()
    )


ADULT_TTL = 12 * 3600               # elenco dei titoli per adulti: si riscarica due volte al giorno
_adult = [0.0, frozenset()]


def _adult_ids():
    """Id dei titoli per adulti (archivio con adult=1, tutte le pagine). Ultimi episodi e
    ricerca non dicono se un titolo è per adulti: li riconosce questo elenco (AU._visible). Se
    l'archivio non risponde resta l'ultimo elenco buono."""
    if time.monotonic() - _adult[0] < ADULT_TTL and _adult[1]:
        return _adult[1]
    try:
        first = _d(_api("/api/archive", {"adult": 1}))
        pages = [first] + [_d(_api("/api/archive", {"adult": 1, "page": n}))
                           for n in range(2, min(_int(first.get("last_page"), 1), 20) + 1)]
        ids = frozenset(_int(x.get("id")) for p in pages for x in _l(p.get("data")) if _d(x).get("id"))
        if ids:
            _adult[:] = [time.monotonic(), ids]
    except Exception as ex:
        log.warning("AnimeUnity elenco dei titoli per adulti: %s", ex)
    return _adult[1]


def fetch_home():
    data = _api("/api/home/latest-episodes", {
        "page": 1,
        "per_page": 20,
    })

    items = []
    seen = set()
    for entry in _l(_d(data).get("data")):
        anime = _d(_d(entry).get("episode")).get("anime")
        anime = _d(anime)

        if not anime.get("id") or not anime.get("slug"):
            continue

        sid = _sid(anime)
        if sid in seen:
            continue

        seen.add(sid)
        items.append(_parse_series(anime))

    return [{
        "id": "ultimi-episodi",
        "title": "Ultimi episodi",
        "items": items,
    }] if items else []


# Righe della scheda ANIME: (id, titolo, indirizzo dell'API, parametri). I generi hanno gli id
# dell'archivio del sito (pagina /archive, "animeGenres"); fuori quelli per adulti. L'archivio
# di serie è in ordine alfabetico: sort_by=views mette in cima i più visti.
ANIME_RAILS = [
    ("in-corso", "In corso", "/api/archive", {"status": "ongoing", "sort_by": "views"}),
    ("popolari", "I più popolari", "/api/top-anime", {}),
] + [(f"genere-{gid}", name, "/api/archive", {"genres[]": gid, "sort_by": "views"}) for gid, name in [
    (1, "Azione"), (2, "Avventura"), (5, "Commedia"), (9, "Fantasy"), (18, "Isekai"),
    (32, "Romantici"), (38, "Shounen"), (35, "Fantascienza"), (43, "Sovrannaturale"),
    (26, "Mistero"), (39, "Slice of life"), (41, "Sport"), (23, "Mecha"), (17, "Horror"),
]]


def _anime_list(data):
    """Anime di una risposta a pagine dell'API (archivio, classifica)."""
    return [_parse_series(x) for x in _l(_d(data).get("data")) if _d(x).get("id") and _d(x).get("slug")]


def fetch_anime():
    def rail(r):
        rid, title, path, params = r
        try:
            return {"id": rid, "title": title, "items": _anime_list(_api(path, params))}
        except Exception as ex:                    # una riga che non risponde non ferma le altre
            log.warning("AnimeUnity riga %s: %s", rid, ex)
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = [r for r in pool.map(rail, ANIME_RAILS) if r and r["items"]]
    if not rows:
        raise RuntimeError("nessuna riga della scheda ANIME disponibile")
    return rows


def fetch_search(query):
    data = _api("/api/search", {"q": query})

    return [
        _parse_series(x)
        for x in _l(_d(data).get("data"))
        if _d(x).get("id") and _d(x).get("slug")
    ]


def fetch_series(sid, season=None):
    # L'identificativo è nel formato "1234-slug".
    raw_sid = _s(sid)
    anime_id = raw_sid.split("-", 1)[0]

    if not anime_id.isdigit():
        raise ValueError(f"ID anime non valido: {sid}")

    # Metadati (descrizione, immagini, generi) dalla pagina dell'anime; se non risponde, dalla
    # ricerca per nome come ripiego.
    slug = raw_sid.split("-", 1)[1] if "-" in raw_sid else ""
    try:
        anime = _d(_page(f"{EPISODE_PATH}{raw_sid}").get("anime")) or None
    except Exception as ex:
        log.warning("AnimeUnity pagina di %s: %s", raw_sid, ex)
        anime = None
    if anime is None:
        data = _api("/api/search", {"q": slug or anime_id})
        anime = next((x for x in _l(_d(data).get("data")) if str(_d(x).get("id")) == anime_id), None)

    if anime is None:
        anime = {
            "id": int(anime_id),
            "slug": slug or anime_id,
            "title": slug.replace("-", " ").title() if slug else anime_id,
        }

    series = _parse_series(anime)
    canonical_sid = series["id"]

    episodes = []
    start = 0
    total = None
    tab_size = 120

    # Recupera tutte le finestre dell'API.
    while total is None or start < total:
        page = _api(
            f"/api/anime/{anime_id}/episodes",
            {"start": start},
        )

        entries = _l(_d(page).get("episodes"))
        total = _int(page.get("total"), 0)
        tab_size = max(1, _int(page.get("tab_size"), 120))

        for entry in entries:
            ep = _parse_episode(
                entry,
                canonical_sid,
                series.get("poster", ""),
            )
            if ep:
                episodes.append(ep)

        if not entries or total <= 0:
            break

        start += tab_size

    # Ordine dal più recente al meno recente.
    episodes.sort(
        key=lambda e: e["n"] if e["n"] is not None else -1,
        reverse=True,
    )

    return series, episodes


def fetch_details(sid):
    """Descrizione, generi e immagini di un anime (dalla sua pagina), senza gli episodi: per i
    titoli che arrivano senza descrizione (Ultimi episodi, ricerca, Continua a guardare)."""
    sid = _s(sid)
    if not sid.split("-", 1)[0].isdigit():
        raise ValueError(f"ID anime non valido: {sid}")
    anime = _d(_page(f"{EPISODE_PATH}{sid}").get("anime"))
    if not anime:
        raise ValueError(f"anime non trovato: {sid}")
    return _parse_series(anime)


def resolve_episode(url):
    """Il player dell'episodio da aprire a schermo intero: (indirizzo, provenienza).
    La pagina dell'episodio ha il video in un riquadro di vixcloud a metà pagina, dove tvbox non
    lo raggiunge; il player aperto da solo invece riempie lo schermo, ma risponde 403 se non si
    dichiara di arrivare da AnimeUnity (referrer)."""
    path = urllib.parse.urlparse(url).path
    embed = _s(_page(path).get("embedUrl"))
    p = urllib.parse.urlparse(embed)
    if p.scheme != "https" or not p.hostname or "/embed/" not in p.path:
        raise ValueError(f"player non trovato nella pagina {path}")
    return embed, BASE_URL + "/"


def site_login(opener, jar, username, password):
    return {
        "ok": False,
        "error": "AnimeUnity non richiede l'accesso per il catalogo pubblico",
    }


def site_user(cookie_header):
    return None


# ======================================================================================
# 2. LA CLASSE AU — già pronta (GET /api/au?...)
# ======================================================================================

TODO_MSG = "Connettore AnimeUnity non ancora scritto"


def is_session_cookie(name):
    return any(name == c or (c.endswith("_") and name.startswith(c)) for c in SESSION_COOKIES)


class AU:
    def __init__(self, prefs, cdp=None):
        self.prefs = prefs
        self.cdp = cdp                      # Chrome della TV: cookie dell'accesso
        self.lock = threading.Lock()
        self.cache = {}                     # chiave -> (istante, dati)
        self._login = None                  # (istante, stato)

    def _cached(self, key, ttl, fn):
        """Dati dalla cache se recenti; altrimenti fn(). Se fn fallisce resta l'ultimo dato buono."""
        with self.lock:
            c = self.cache.get(key)
        if c and time.monotonic() - c[0] < ttl:
            return c[1]
        try:
            d = fn()
        except NotImplementedError:
            raise
        except Exception as ex:
            log.warning("AnimeUnity %s non disponibile: %s", key, ex)
            if c:
                return c[1]
            raise
        with self.lock:
            self.cache[key] = (time.monotonic(), d)
        return d

    # ---------- titoli per adulti: si vedono solo se l'utente lo sceglie (prefs "au_adult") ----------
    def _visible(self, items):
        if self.prefs.get("au_adult"):
            return items
        adult = _adult_ids()
        return [x for x in items if not x.get("adult") and _int(str(x.get("id", "")).split("-", 1)[0]) not in adult]

    # ---------- righe: GET /api/au?page=home|anime ----------
    def rails(self, page=None):
        page = page if page in ("home", "anime") else "home"
        out, error = [], None
        if page == "home":
            hist = self.history()
            if hist:
                out.append({"id": "continua", "page": "home", "title": "Continua a guardare", "items": hist})
        try:
            rows = self._cached("righe:" + page, RAIL_TTL, fetch_home if page == "home" else fetch_anime)
            for r in rows or []:
                items = self._visible([x for x in r.get("items") or [] if x.get("id") and x.get("title")])
                if items:
                    out.append({"id": str(r.get("id") or r.get("title")), "page": page,
                                "title": r.get("title") or "", "items": items})
        except NotImplementedError as ex:
            log.info("AnimeUnity: %s da scrivere", ex)
            error = TODO_MSG
        except Exception:
            error = "Catalogo non disponibile"
        res = {"page": page, "rails": out, "login": self.login_state()}
        if error and not out:
            res["error"] = error
        return res

    # ---------- ricerca: GET /api/au?action=search&q=... ----------
    def search(self, query):
        query = (query or "").strip()[:100]
        if not query:
            return {"query": "", "items": []}
        try:
            items = self._visible([x for x in fetch_search(query) or [] if x.get("id") and x.get("title")])
            return {"query": query, "items": items}
        except NotImplementedError:
            return {"query": query, "items": [], "error": TODO_MSG}
        except Exception as ex:
            log.warning("AnimeUnity ricerca '%s': %s", query, ex)
            return {"query": query, "items": [], "error": "Ricerca temporaneamente non disponibile"}

    # ---------- descrizione di un titolo evidenziato: GET /api/au?action=details&id=... ----------
    def details(self, sid):
        """Descrizione, generi e immagini di un titolo che ne arriva senza (si chiede quando lo si
        evidenzia; in cache per un giorno). {} se il connettore non lo sa fare o il sito non risponde."""
        try:
            s = self._cached(f"dettagli:{sid}", DETAILS_TTL, lambda: fetch_details(sid))
        except Exception:
            return {}
        return {k: s.get(k) for k in ("desc", "genres", "category", "poster", "hero", "logo") if s.get(k)}

    # ---------- un anime: GET /api/au?action=series&id=...&season=... ----------
    def series(self, sid, season=None):
        group = season if season and re.fullmatch(r"\d+-\d+", str(season)) else None   # "101-200"
        real = None if group else season
        try:
            s, eps = self._cached(f"serie:{sid}:{real}", SERIES_TTL, lambda: fetch_series(sid, real))
        except NotImplementedError:
            return {"error": TODO_MSG, "login": self.login_state()}
        except Exception:
            return {"error": "Non disponibile", "login": self.login_state()}
        eps = [e for e in eps or [] if is_episode_url(e.get("url"))]
        h = next((h for h in self.prefs.get("au_history") if h.get("series") == str(sid)), None)
        last = h.get("episode") if h else None
        if len(s.get("seasons") or []) <= 1 and len(eps) > EP_GROUP * 3 // 2:
            s, eps, season = self._grouped(s, eps, group, last)
        return dict(s, season=str(season) if season else s.get("current"), episodes=eps, last=last)

    @staticmethod
    def _grouped(s, eps, group, last):
        """Serie lunghissima senza stagioni: gli episodi a gruppi di EP_GROUP come "stagioni"
        ("1–100", "101–200", …), così la pagina resta leggera e si arriva presto all'episodio.
        Si apre sul gruppo chiesto, se no su quello dell'ultimo visto, se no sui più recenti."""
        nums = [e["n"] for e in eps if isinstance(e.get("n"), int)]
        if not nums:
            return s, eps, None
        top = max(nums)
        bounds = [(a, min(a + EP_GROUP - 1, top)) for a in range(1, top + 1, EP_GROUP)]
        seasons = [{"id": f"{a}-{b}", "n": k + 1, "title": f"{a}–{b}"} for k, (a, b) in enumerate(bounds)]
        seen = next((e["n"] for e in eps if e["id"] == last and isinstance(e.get("n"), int)), None)
        pick = group or next((f"{a}-{b}" for a, b in bounds if seen is not None and a <= seen <= b),
                             seasons[-1]["id"])
        a, b = (int(x) for x in pick.split("-"))
        inside = [e for e in eps if isinstance(e.get("n"), int) and a <= e["n"] <= b]
        if pick == seasons[-1]["id"]:
            inside += [e for e in eps if not isinstance(e.get("n"), int)]     # senza numero: in fondo
        return dict(s, seasons=seasons, current=pick, grouped=True, total=len(eps)), inside, pick

    # ---------- apertura di un episodio: GET /api/au?action=play ----------
    def play_target(self, url):
        """Cosa aprire a schermo per l'episodio url: (indirizzo, provenienza). Con resolve_episode
        nel connettore il player da solo; altrimenti (o se non risponde) la pagina dell'episodio."""
        try:
            return resolve_episode(url)
        except NotImplementedError:
            return url, None
        except Exception as ex:
            log.warning("AnimeUnity: player di %s non trovato, apro la pagina: %s", url, ex)
            return url, None

    # ---------- Continua a guardare ----------
    def history(self):
        return [{"id": h["series"], "title": h["title"], "poster": h["poster"], "hero": h.get("hero", ""),
                 "logo": h.get("logo", ""), "desc": "",          # la trama arriva con details()
                 "sub": h.get("ep") or (f"Ep. {h['n']}" if h.get("n") is not None else ""),
                 "episode": h["episode"]}
                for h in self.prefs.get("au_history")]

    def remember(self, q):
        """Ricorda l'episodio aperto (in cima a "Continua a guardare", una voce per anime)."""
        h = {"series": q.get("series", ""), "title": (q.get("title") or "")[:60],
             "poster": q.get("poster", ""), "hero": q.get("hero", ""), "logo": q.get("logo", ""),
             "ep": (q.get("ep") or "")[:60], "episode": q.get("episode", ""),
             "n": int(q["n"]) if (q.get("n") or "").isdigit() else None, "t": int(time.time())}
        if h["series"]:
            self.prefs.update("au_history", lambda l: ([h] + [x for x in l if x["series"] != h["series"]])[:HISTORY_MAX])

    # ---------- accesso: GET /api/au?action=status|login|logout ----------
    def _chrome_cookies(self):
        if not self.cdp or not SITE_HOST:
            return []
        try:
            return self.cdp.call("Network.getCookies", {"urls": [BASE_URL + "/"]}).get("cookies", [])
        except Exception as ex:
            log.warning("AnimeUnity: cookie di Chrome non leggibili: %s", ex)
            return []

    def _set_state(self, logged, user=""):
        # available: il connettore prevede un accesso (ha i cookie di sessione da cercare)
        st = {"available": bool(SESSION_COOKIES), "required": LOGIN_REQUIRED, "logged": bool(logged),
              "user": user or ""}
        with self.lock:
            self._login = (time.monotonic(), st)
        return st

    def login_state(self, fresh=False):
        """{"available", "required", "logged", "user"}: dai cookie di Chrome (e dal sito, se il
        connettore ha site_user)."""
        with self.lock:
            cached = self._login
        if not fresh and cached and time.monotonic() - cached[0] < LOGIN_STATUS_TTL:
            return cached[1]
        cookies = self._chrome_cookies()
        if not SESSION_COOKIES or not any(is_session_cookie(c.get("name", "")) for c in cookies):
            return self._set_state(False)
        try:
            user = site_user("; ".join(f"{c['name']}={c['value']}" for c in cookies))
            return self._set_state(bool(user), user)
        except NotImplementedError:
            return self._set_state(True, cached[1]["user"] if cached else "")
        except Exception as ex:                          # sito irraggiungibile: si resta come prima
            log.warning("AnimeUnity: stato dell'accesso non verificabile: %s", ex)
            return cached[1] if cached else self._set_state(True)

    def login(self, username, password):
        username, password = (username or "").strip(), password or ""
        if not username or not password:
            return {"ok": False, "error": "Scrivi utente e password"}
        if not self.cdp:
            return {"ok": False, "error": "Chrome non raggiungibile"}
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        opener.addheaders = [("User-Agent", DESKTOP_UA), ("Accept-Language", "it-IT,it;q=0.9")]
        try:
            r = site_login(opener, jar, username, password) or {}
        except NotImplementedError:
            return {"ok": False, "error": TODO_MSG}
        except Exception as ex:
            log.warning("AnimeUnity: accesso non riuscito: %s", ex)
            return {"ok": False, "error": "Il sito non risponde, riprova tra poco"}
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error") or "Accesso non riuscito"}
        try:
            self._clear_chrome_cookies()
            for c in jar:                                # la sessione va nel Chrome della TV
                p = {"name": c.name, "value": c.value, "url": BASE_URL + (c.path or "/"),
                     "path": c.path or "/", "secure": bool(c.secure),
                     "httpOnly": c.has_nonstandard_attr("HttpOnly")}
                if c.domain_specified:
                    p["domain"] = c.domain
                if c.expires:
                    p["expires"] = c.expires
                self.cdp.call("Network.setCookie", p)
        except Exception as ex:
            log.warning("AnimeUnity: cookie non copiati in Chrome: %s", ex)
            return {"ok": False, "error": "Accesso riuscito, ma Chrome non ha salvato la sessione"}
        log.info("AnimeUnity: accesso riuscito")
        return dict(self._set_state(True, r.get("user") or username), ok=True)

    def _clear_chrome_cookies(self):
        for c in self._chrome_cookies():
            self.cdp.call("Network.deleteCookies", {"name": c["name"], "domain": c["domain"],
                                                    "path": c.get("path", "/")})

    def logout(self):
        """Esce dall'account: via i cookie del sito da Chrome."""
        try:
            self._clear_chrome_cookies()
        except Exception as ex:
            log.warning("AnimeUnity: uscita: %s", ex)
        return self._set_state(False)

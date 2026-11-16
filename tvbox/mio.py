"""Connettore per tvbox.
"""

import concurrent.futures
import http.cookiejar
import json
import html
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .util import DESKTOP_UA, USER_DIR, log

try:
    from scuapi import API as SCAPI
except ImportError:
    SCAPI = None

NAME = "mio-sito"
SITE_HOST = "streamingunity.day"
BASE_URL = f"https://{SITE_HOST}"
CDN_URL = f"https://cdn.{SITE_HOST}/images/"
EPISODE_PATH = "/it/watch/"

# Slider ufficiali restituiti da SU.
SLIDERS_URL = f"{BASE_URL}/api/sliders/fetch?lang=it"
SLIDERS_PAYLOAD = {
    "sliders": [
        {"name": "trending", "genre": None},
        {"name": "latest", "genre": None},
        {"name": "top10", "genre": None},
    ]
}

# ID e nomi ricavati dal catalogo generi di SU.
# L'archivio viene interrogato con /it/archive?genre[]=ID.
GENRES = [
    (4, "Azione", "movie"),
    (13, "Action & Adventure", "tv"),
    (11, "Avventura", "movie"),
    (19, "Animazione", "all"),
    (12, "Commedia", "all"),
    (2, "Crime", "all"),
    (24, "Documentario", "all"),
    (1, "Dramma", "all"),
    (16, "Famiglia", "all"),
    (8, "Fantasy", "movie"),
    (22, "Storia", "movie"),
    (7, "Horror", "movie"),
    (25, "Kids", "tv"),
    (26, "Korean drama", "all"),
    (14, "Musica", "movie"),
    (6, "Mistero", "all"),
    (18, "Reality", "tv"),
    (15, "Romance", "all"),
    (3, "Sci-Fi & Fantasy", "tv"),
    (10, "Fantascienza", "movie"),
    (23, "Soap", "tv"),
    (5, "Thriller", "movie"),
    (9, "Guerra", "movie"),
    (17, "War & Politics", "tv"),
    (20, "Western", "all"),
]

LOGIN_URL = ""
LOGIN_REQUIRED = False
COOKIE_URLS = []
LOGIN_COOKIE = ""
TOKEN_JS = ""

RAIL_TTL = 1800
SERIES_TTL = 1800
EPISODES_TTL = 900
HISTORY_MAX = 12
TOKEN_FILE = os.path.join(USER_DIR, "mio-token.json")


def is_episode_url(u):
    """Accetta esclusivamente pagine episodio HTTPS del dominio configurato."""
    parsed = urllib.parse.urlparse(u or "")
    return (
        bool(SITE_HOST)
        and parsed.scheme == "https"
        and parsed.hostname == SITE_HOST
        and parsed.path.startswith(EPISODE_PATH)
    )


def _d(value):
    return value if isinstance(value, dict) else {}


def _l(value):
    return value if isinstance(value, list) else []


def _s(value):
    return str(value).strip() if value is not None else ""


def _first(d, *keys, default=None):
    d = _d(d)
    for key in keys:
        value = d.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _slug(e):
    """Restituisce l'identificativo id-slug."""
    e = _d(e)
    ident = _s(e.get("id"))
    slug = _s(e.get("slug"))
    if ident and slug:
        return f"{ident}-{slug}"
    raw = _s(e.get("url"))
    if raw:
        path = urllib.parse.urlparse(raw).path.rstrip("/")
        if path:
            return path.rsplit("/", 1)[-1]
    return ident or slug


def _image_url(image):
    image = _d(image)
    absolute = _s(_first(image, "url", "src", "original_url_field", "original_url"))
    if absolute.startswith("https://"):
        return absolute
    if absolute.startswith("http://"):
        return "https://" + absolute[7:]
    filename = _s(image.get("filename"))
    return CDN_URL + urllib.parse.quote(filename) if filename else ""


def _images(e):
    return [_d(x) for x in _l(_d(e).get("images"))]


def _pick_image(e, *wanted):
    images = _images(e)
    for kind in wanted:
        for item in images:
            if _s(item.get("type")).lower() == kind:
                return _image_url(item)
    return _image_url(images[0]) if images else ""


def _date_ms(value):
    if value in (None, "", 0):
        return 0
    try:
        if isinstance(value, (int, float)):
            return int(value if value > 10**12 else value * 1000)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError, OverflowError):
        return 0


def _duration_seconds(value):
    try:
        # restituisce la durata in minuti.
        return max(0, int(float(value) * 60)) if value not in (None, "") else 0
    except (ValueError, TypeError):
        return 0


def is_logged_in(auth):
    return False


def auth_headers(auth):
    return {}


def rail_url(param):
    # Compatibilità con eventuali chiamanti precedenti.
    return SLIDERS_URL if param == "sliders" else ""


def rail_entries(data):
    """Compatibilità: estrae i titoli da una risposta slider."""
    if isinstance(data, list):
        return data
    data = _d(data)
    return _l(data.get("titles"))


def genre_url(genre_id):
    """URL dell'archivio filtrato per un singolo genere."""
    query = urllib.parse.urlencode({"genre[]": int(genre_id)})
    return f"{BASE_URL}/it/archive?{query}"


def genre_entries(data):
    """Estrae i titoli dalla risposta Inertia dell'archivio."""
    data = _d(data)
    props = _d(data.get("props"))
    return _l(props.get("titles"))


def series_url(sid):
    # richiede l'identificativo composto id-slug.
    return _s(sid)


def series_entry(data):
    data = _d(data)
    return data if _first(data, "id", "name") else None


def episodes_url(series, season):
    # scarica già le stagioni e crea episodeList.
    return ""


def episode_entries(data):
    return _l(_d(data).get("episodeList"))


def parse_series(e):
    e = _d(e)
    sid = _slug(e)
    kind = _s(e.get("type")).lower()
    is_movie = kind in ("movie", "film")

    translations = {
        _s(item.get("key")): _s(item.get("value"))
        for item in _l(e.get("translations"))
        if _s(item.get("key"))
    }

    raw_seasons = _l(e.get("seasons"))
    seasons = []
    for index, raw in enumerate(raw_seasons, 1):
        raw = _d(raw)
        number = raw.get("number") or raw.get("n") or index
        try:
            number = int(number)
        except (ValueError, TypeError):
            number = index
        seasons.append({
            "id": str(number),
            "n": number,
            "title": _s(raw.get("name") or raw.get("title") or f"Stagione {number}"),
        })

    if is_movie:
        seasons = [{"id": "movie", "n": 1, "title": "Film"}]
    elif not seasons:
        try:
            count = max(1, int(e.get("seasons_count") or 1))
        except (TypeError, ValueError):
            count = 1
        seasons = [
            {"id": str(n), "n": n, "title": f"Stagione {n}"}
            for n in range(1, count + 1)
        ]

    return {
        "id": sid,
        "title": _s(e.get("name") or e.get("title") or translations.get("name")),
        "poster": _pick_image(e, "poster", "cover_mobile", "cover"),
        "hero": _pick_image(e, "background", "cover"),
        "logo": _pick_image(e, "logo"),
        "desc": _s(e.get("plot") or e.get("description") or translations.get("plot")),
        "category": "Film" if is_movie else "Serie TV",
        "genres": [
            str(x.get("name") if isinstance(x, dict) else x)
            for x in _l(e.get("tags"))
            if x
        ],
        "seasons": seasons,
        "current": seasons[-1]["id"] if seasons else None,
    }


def parse_episode(e):
    e = _d(e)
    eid = _s(e.get("id"))
    raw_url = _s(e.get("url"))
    url = ""

    if raw_url:
        parsed = urllib.parse.urlparse(raw_url)
        if (
            parsed.scheme == "https"
            and parsed.hostname == SITE_HOST
            and parsed.path.startswith(EPISODE_PATH)
        ):
            url = raw_url

    if not url and eid and e.get("title_id"):
        url = (
            f"{BASE_URL}{EPISODE_PATH}{_s(e.get('title_id'))}"
            f"?e={urllib.parse.quote(eid)}"
        )

    number = e.get("episode")
    try:
        number = int(number) if number is not None else None
    except (TypeError, ValueError):
        number = None

    image = ""
    for item in _images(e):
        if _s(item.get("type")).lower() in ("cover", "still", "poster"):
            image = _image_url(item)
            break
    if not image:
        image = _image_url(_images(e)[0]) if _images(e) else ""

    title = _s(e.get("name") or e.get("title"))
    if not title:
        title = f"Episodio {number}" if number is not None else "Episodio"

    return {
        "id": eid,
        "url": url,
        "title": title,
        "n": number,
        "desc": _s(e.get("description") or e.get("plot")),
        "dur": _duration_seconds(e.get("duration")),
        "date": _date_ms(e.get("release_date") or e.get("date")),
        "channel": "",
        "image": image,
    }


def episodes_of(entries, season=None, series_id=None):
    selected = []
    for raw in _l(entries):
        raw = dict(_d(raw))
        if season is not None:
            season_number = _d(season).get("n", season)
            if str(raw.get("season", 1)) != str(season_number):
                continue
        parsed = parse_episode(raw)
        if parsed["url"]:
            selected.append(parsed)

    return sorted(
        selected,
        key=lambda x: (
            x["n"] if x["n"] is not None else -1,
            x["date"],
        ),
        reverse=True,
    )


def pick_season(series, season=None):
    seasons = _l(_d(series).get("seasons"))
    if not seasons:
        return None

    return (
        next((x for x in seasons if season and str(x["id"]) == str(season)), None)
        or next(
            (x for x in seasons if str(x["id"]) == str(series.get("current"))),
            None,
        )
        or seasons[-1]
    )


def get_json_auth(url, headers=None, timeout=12):
    """GET tradizionale usato per le pagine pubbliche/Inertia."""
    request_headers = {
        "User-Agent": DESKTOP_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        "Referer": f"{BASE_URL}/",
    }
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as ex:
        raw = ex.read().decode("utf-8", "replace")
        log.warning(
            "SU HTTP %s - URL: %s - Headers: %s - Body: %s",
            ex.code, url, dict(ex.headers), raw[:2000]
        )
        raise

    try:
        return json.loads(raw)
    except ValueError:
        match = re.search(r'data-page="([^"]+)"', raw)
        if match:
            try:
                return json.loads(html.unescape(match.group(1)))
            except ValueError:
                pass
    return {}


def get_sliders_auth(timeout=15):
    """POST agli slider con cookie di sessione e token CSRF Laravel."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar)
    )

    common_headers = {
        "User-Agent": DESKTOP_UA,
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    # Inizializza la sessione: Laravel imposta XSRF-TOKEN e session cookie.
    init_request = urllib.request.Request(
        f"{BASE_URL}/it",
        headers={
            **common_headers,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with opener.open(init_request, timeout=timeout) as response:
        response.read()

    xsrf_cookie = next(
        (cookie.value for cookie in jar if cookie.name == "XSRF-TOKEN"),
        None,
    )
    if not xsrf_cookie:
        raise RuntimeError("SU non ha restituito il cookie XSRF-TOKEN")

    # Il browser invia nell'header il valore URL-decoded del cookie XSRF-TOKEN.
    xsrf_token = urllib.parse.unquote(xsrf_cookie)
    payload = json.dumps(SLIDERS_PAYLOAD).encode("utf-8")

    post_request = urllib.request.Request(
        SLIDERS_URL,
        data=payload,
        headers={
            **common_headers,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/it/",
            "X-XSRF-TOKEN": xsrf_token,
        },
        method="POST",
    )

    with opener.open(post_request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", "replace")

    data = json.loads(raw)
    if isinstance(data, dict):
        # Alcune risposte possono racchiudere l'array in una proprietà.
        data = data.get("sliders", data.get("data", []))

    if not isinstance(data, list):
        raise ValueError("La risposta dell'endpoint slider non è una lista")

    return data


class Mio:
    def __init__(self, prefs, cdp=None):
        self.prefs = prefs
        self.cdp = cdp
        self.lock = threading.Lock()
        self.cache = {}
        self._api = None
        self._api_error = None
        self._warm_lock = threading.Lock()

    def _client(self):
        if self._api is None and self._api_error is None:
            if SCAPI is None:
                self._api_error = (
                    "Dipendenza mancante: installa scapi"
                )
            else:
                try:
                    self._api = SCAPI(
                        SITE_HOST,
                        user_agent=DESKTOP_UA,
                    )
                except Exception as ex:
                    self._api_error = str(ex)
        return self._api

    def login_state(self, fresh=False):
        return {"available": False, "logged": False, "required": False}

    def auth(self, fresh=False):
        return {"cookies": {}, "token": None}

    def after_login(self):
        return self.login_state(fresh=True)

    def logout(self):
        try:
            os.remove(TOKEN_FILE)
        except OSError:
            pass
        return self.login_state(fresh=True)

    def _get(self, key, url, ttl):
        if not url:
            return {}

        with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < ttl:
                return cached[1]

        try:
            if key == "sliders":
                data = get_sliders_auth()
            elif key.startswith("serie:"):
                client = self._client()
                if client is None:
                    raise RuntimeError(
                        self._api_error or "scapi non disponibile"
                    )
                data = client.load(url)
            else:
                data = get_json_auth(url)

            if not isinstance(data, (dict, list)) or not data:
                raise ValueError("risposta vuota o non riconosciuta")

        except Exception as ex:
            log.warning("%s %s non disponibile: %s", NAME, key, ex)
            return cached[1] if cached else {}

        with self.lock:
            self.cache[key] = (time.monotonic(), data)

        return data

    def _load_genre_rail(self, genre):
        genre_id, genre_name, genre_type = genre
        key = f"genere:{genre_id}"

        data = self._get(key, genre_url(genre_id), RAIL_TTL)
        entries = genre_entries(data)

        movies = []
        series = []

        for entry in entries:
            item = parse_series(entry)

            if not item["id"] or not item["title"] or not item["poster"]:
                continue

            if item["category"] == "Film":
                if genre_type in ("movie", "all"):
                    movies.append(item)
            else:
                if genre_type in ("tv", "all"):
                    series.append(item)

        rails = []

        if movies:
            rails.append({
                "id": f"genere-film:{genre_id}",
                "page": "films",
                "title": genre_name,
                "items": movies,
            })

        if series:
            rails.append({
                "id": f"genere-serie:{genre_id}",
                "page": "series",
                "title": genre_name,
                "items": series,
            })

        return rails
    # ---------- righe: GET /api/mio?page=home|series|films ----------
    def rails(self, page=None):
        """HOME: Continua a guardare + i tre slider. SERIE TV / FILM: una riga per genere.
        Le pagine si caricano a parte: la HOME non aspetta le 25 richieste dei generi."""
        page = page if page in ("home", "series", "films") else "home"
        if page == "home":
            out = self._home_rails()
            self._warm_genres()                  # i generi intanto si scaricano in sottofondo
        else:
            out = [r for r in self._genre_rails() if r["page"] == page]
        return {"page": page, "rails": out, "login": self.login_state()}

    def _home_rails(self):
        out = []
        hist = self.history()
        if hist:
            out.append({"id": "continua", "page": "home",
                        "title": "Continua a guardare", "items": hist})

        slider_titles = {
            "trending": "I titoli del momento",
            "latest": "Aggiunti di recente",
            "top10": "Top ten titoli di oggi",
        }
        try:
            for slider in _l(self._get("sliders", SLIDERS_URL, RAIL_TTL)):
                slider = _d(slider)
                rid = _s(slider.get("name"))
                if rid not in slider_titles:
                    continue
                items = [parse_series(e) for e in _l(slider.get("titles"))]
                items = [x for x in items
                         if x["id"] and x["title"] and x["poster"] and x["seasons"]]
                if items:
                    out.append({"id": rid, "page": "home",
                                "title": slider_titles[rid], "items": items})
        except Exception as ex:
            log.warning("%s caricamento slider: %s", NAME, ex)
        return out

    def _genre_rails(self):
        """Tutte le righe per genere (film e serie insieme): le richieste vanno in cache,
        quindi la seconda scheda aperta non scarica di nuovo nulla."""
        out = []
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                for rails in pool.map(self._load_genre_rail, GENRES):
                    out.extend(rails)
        except Exception as ex:
            log.warning("%s caricamento catalogo per genere: %s", NAME, ex)
        return out

    def _warm_genres(self):
        """Scarica i generi in un thread, uno solo alla volta (niente doppioni)."""
        if not self._warm_lock.acquire(blocking=False):
            return

        def run():
            try:
                self._genre_rails()
            finally:
                self._warm_lock.release()

        threading.Thread(target=run, name="mio-generi", daemon=True).start()

    def series(self, sid, season=None):
        try:
            entry = series_entry(
                self._get(
                    "serie:" + str(sid),
                    series_url(sid),
                    SERIES_TTL,
                )
            )
            if not entry:
                return {"error": "Titolo non trovato"}

            parsed = parse_series(entry)
            selected = pick_season(parsed, season)

            if parsed["category"] == "Film":
                movie_id = _s(entry.get("id"))
                movie_url = f"{BASE_URL}{EPISODE_PATH}{movie_id}"
                eps = [{
                    "id": movie_id,
                    "url": movie_url,
                    "title": parsed["title"],
                    "n": None,
                    "desc": parsed["desc"],
                    "dur": _duration_seconds(entry.get("duration")),
                    "date": _date_ms(entry.get("release_date")),
                    "channel": "",
                    "image": parsed["hero"] or parsed["poster"],
                }]
                selected_id = "movie"
            else:
                all_eps = episode_entries(entry)
                eps = episodes_of(all_eps, selected, sid)
                selected_id = selected["id"] if selected else None

            prefs_history = self.prefs.get("mio_history") or []
            last = next(
                (h for h in prefs_history if h.get("series") == sid),
                None,
            )

            return dict(
                parsed,
                season=selected_id,
                episodes=eps,
                last=last.get("episode") if last else None,
            )

        except Exception as ex:
            log.warning("%s serie %s: %s", NAME, sid, ex)
            return {"error": "Non disponibile"}

    def history(self):
        return [
            {
                "id": h.get("series", ""),
                "title": h.get("title", ""),
                "poster": h.get("poster", ""),
                "hero": h.get("hero", ""),
                "logo": h.get("logo", ""),
                "desc": h.get("ep", ""),
                "sub": h.get("ep") or (
                    f"Ep. {h['n']}" if h.get("n") is not None else ""
                ),
                "episode": h.get("episode", ""),
            }
            for h in (self.prefs.get("mio_history") or [])
        ]

    def remember(self, q):
        q = _d(q)
        h = {
            "series": _s(q.get("series")),
            "title": _s(q.get("title"))[:60],
            "poster": q.get("poster", ""),
            "hero": q.get("hero", ""),
            "logo": q.get("logo", ""),
            "ep": _s(q.get("ep"))[:60],
            "episode": _s(q.get("episode")),
            "n": int(q["n"]) if _s(q.get("n")).isdigit() else None,
            "t": int(time.time()),
        }
        if not h["series"]:
            return

        self.prefs.update(
            "mio_history",
            lambda items: (
                [h] + [
                    x for x in items
                    if x.get("series") != h["series"]
                ]
            )[:HISTORY_MAX],
        )

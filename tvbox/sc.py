"""Connettore per tvbox.
"""

import concurrent.futures
import http.cookiejar
import json
import html
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .util import DESKTOP_UA, log

try:
    from vendor.scuapi import API as SCAPI
except ImportError:
    SCAPI = None

NAME = "sc-sito"
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

# ---------- accesso (login) ----------
# L'accesso lo fa tvd, non la pagina del sito: utente e password arrivano dalla schermata di
# tvbox, tvd li manda al modulo di login del sito (Laravel + Inertia, come il browser) e copia
# i cookie della sessione nel Chrome della TV, dove li usa il player del sito. La password non
# si salva da nessuna parte: resta il cookie "ricordami" del sito, come spuntandolo nel browser.
LOGIN_URL = f"{BASE_URL}/login"
LOGIN_REQUIRED = True            # senza accesso la sezione mostra solo la schermata di accesso
LOGIN_STATUS_TTL = 300           # lo stato (collegato o no) si ricontrolla sul sito ogni 5 minuti
SESSION_COOKIES = ("streamingcommunity_session", "remember_web_")   # nomi (o inizi) dei cookie di sessione

RAIL_TTL = 1800
SERIES_TTL = 1800
EPISODES_TTL = 900
HISTORY_MAX = 12


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


def page_props(text):
    """Dati della pagina Inertia (attributo data-page dell'HTML, o la risposta JSON)."""
    text = text or ""
    if text.lstrip().startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            data = {}
    else:
        m = re.search(r'data-page="([^"]*)"', text)
        try:
            data = json.loads(html.unescape(m.group(1))) if m else {}
        except ValueError:
            data = {}
    return _d(data)


def page_user(props):
    """L'utente collegato secondo la pagina del sito, o None."""
    user = _d(_d(_d(props.get("props")).get("auth")).get("user"))
    return user or None


def login_error(props):
    """Primo messaggio d'errore del modulo di accesso (es. "Credenziali non valide.")."""
    p = _d(props.get("props"))
    for v in _d(p.get("errors")).values():
        v = v[0] if isinstance(v, list) and v else v
        if _s(v):
            return _s(v)
    return _s(_d(p.get("flash")).get("error"))


def is_session_cookie(name):
    return any(name == c or (c.endswith("_") and name.startswith(c)) for c in SESSION_COOKIES)


def genre_url(genre_id, kind=None):
    """URL dell'archivio filtrato per un genere: i 60 titoli più visti (sort=views; di base
    l'archivio è per data di uscita). kind "tv" o "movie": solo serie o solo film. Va chiesto
    sempre un tipo: ordinando per visualizzazioni le serie riempiono quasi tutta la lista
    (Azione: 58 serie e 2 film) e la riga dei film resterebbe vuota."""
    params = {"genre[]": int(genre_id), "sort": "views"}
    if kind:
        params["type"] = kind
    return f"{BASE_URL}/it/archive?{urllib.parse.urlencode(params)}"


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


def iframe_url(watch_url):
    """Il riquadro del player di una pagina /it/watch/: /it/iframe/<id>?episode_id=<e> per un
    episodio, /it/iframe/<id> per un film."""
    p = urllib.parse.urlparse(watch_url or "")
    tid = p.path[len(EPISODE_PATH):].strip("/") if p.path.startswith(EPISODE_PATH) else ""
    if not tid.isdigit():
        raise ValueError(f"indirizzo dell'episodio non valido: {watch_url}")
    e = urllib.parse.parse_qs(p.query).get("e", [""])[0]
    return f"{BASE_URL}/it/iframe/{tid}" + (f"?episode_id={urllib.parse.quote(e)}" if e else "")


def resolve_episode(watch_url, timeout=15):
    """Il player dell'episodio da aprire a schermo intero: (indirizzo, provenienza).
    La pagina /it/watch/ ha il video dentro un riquadro (/it/iframe/, che contiene il player di
    vixcloud): tvbox lì non lo vede, quindi niente punto di ripresa né controllo del video.
    Il player aperto da solo invece è la pagina stessa. Il suo indirizzo ha un codice che scade
    (si ricava a ogni apertura) e vale solo se il riquadro si chiede dichiarando di arrivare
    dalla pagina dell'episodio; aprendolo poi si dichiara di arrivare dal riquadro."""
    frame = iframe_url(watch_url)
    req = urllib.request.Request(frame, headers={"User-Agent": DESKTOP_UA, "Referer": watch_url,
                                                 "Accept": "text/html", "Accept-Language": "it-IT,it;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        page = html.unescape(r.read().decode("utf-8", "replace"))
    m = re.search(r'https://vixcloud\.cc/embed/\d+[^"\'<\s]*', page)
    if not m:
        raise ValueError(f"player non trovato in {frame}")
    return m.group(0), frame


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


class SC:
    def __init__(self, prefs, cdp=None):
        self.prefs = prefs
        self.cdp = cdp

        # Il lock globale protegge solo strutture condivise.
        # Le richieste HTTP non vengono eseguite mentre è acquisito.
        self.lock = threading.RLock()
        self.cache = {}

        # Un lock per chiave evita download simultanei dello stesso contenuto.
        self._key_locks = {}

        self._api = None
        self._api_error = None
        self._client_lock = threading.Lock()
        self._warm_lock = threading.Lock()

    def _client(self):
        # Evita che richieste concorrenti inizializzino client distinti.
        with self._client_lock:
            if self._api is None and self._api_error is None:
                if SCAPI is None:
                    self._api_error = "Dipendenza mancante: installa scapi"
                else:
                    try:
                        self._api = SCAPI(
                            SITE_HOST,
                            user_agent=DESKTOP_UA,
                        )
                    except Exception as ex:
                        self._api_error = str(ex)

            return self._api

    # ---------- accesso: GET /api/sc?action=status|login|logout ----------
    def _chrome_cookies(self):
        """Cookie del sito nel Chrome della TV (sono loro a dire se si è collegati)."""
        if not self.cdp:
            return []
        try:
            return self.cdp.call("Network.getCookies", {"urls": [BASE_URL + "/"]}).get("cookies", [])
        except Exception as ex:
            log.warning("sc: cookie di Chrome non leggibili: %s", ex)
            return []

    def _site_user(self, cookies):
        """Chiede al sito chi è collegato con questi cookie: l'utente o None."""
        req = urllib.request.Request(f"{BASE_URL}/it", headers={
            "User-Agent": DESKTOP_UA, "Accept": "text/html",
            "Cookie": "; ".join(f"{c['name']}={c['value']}" for c in cookies)})
        with urllib.request.urlopen(req, timeout=10) as r:
            return page_user(page_props(r.read().decode("utf-8", "replace")))

    def _set_state(self, logged, user=None):
        user = _d(user)
        st = {"available": True, "required": LOGIN_REQUIRED, "logged": bool(logged),
              "user": _s(_first(user, "username", "name", "email", default=""))}
        with self.lock:
            self._login = (time.monotonic(), st)
        return st

    def login_state(self, fresh=False):
        """{"available", "required", "logged", "user"}: dai cookie di Chrome, verificati sul sito."""
        with self.lock:
            cached = getattr(self, "_login", None)
        if not fresh and cached and time.monotonic() - cached[0] < LOGIN_STATUS_TTL:
            return cached[1]
        cookies = self._chrome_cookies()
        if not any(is_session_cookie(c.get("name", "")) for c in cookies):
            return self._set_state(False)
        try:
            user = self._site_user(cookies)
        except Exception as ex:
            # sito irraggiungibile: non si chiude fuori l'utente, si resta come prima
            # (o collegati, se Chrome ha il cookie "ricordami")
            log.warning("sc: stato dell'accesso non verificabile: %s", ex)
            if cached:
                return cached[1]
            return self._set_state(any(c["name"].startswith("remember_web_") for c in cookies))
        return self._set_state(user, user)

    def login(self, username, password):
        """Accesso con utente e password, come il modulo del sito; poi i cookie vanno in Chrome."""
        username, password = _s(username), password or ""
        if not username or not password:
            return {"ok": False, "error": "Scrivi utente e password"}
        if not self.cdp:
            return {"ok": False, "error": "Chrome non raggiungibile"}
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        base = {"User-Agent": DESKTOP_UA, "Accept-Language": "it-IT,it;q=0.9"}
        try:
            with opener.open(urllib.request.Request(LOGIN_URL, headers=base), timeout=15) as r:
                version = _s(page_props(r.read().decode("utf-8", "replace")).get("version"))
            xsrf = next((urllib.parse.unquote(c.value) for c in jar if c.name == "XSRF-TOKEN"), "")
            body = json.dumps({"username": username, "password": password, "remember": True}).encode()
            req = urllib.request.Request(LOGIN_URL, data=body, method="POST", headers={
                **base, "Content-Type": "application/json", "Accept": "text/html, application/xhtml+xml",
                "X-Requested-With": "XMLHttpRequest", "X-Inertia": "true", "X-Inertia-Version": version,
                "X-XSRF-TOKEN": xsrf, "Origin": BASE_URL, "Referer": LOGIN_URL})
            with opener.open(req, timeout=15) as r:
                props = page_props(r.read().decode("utf-8", "replace"))
        except Exception as ex:
            log.warning("sc: accesso non riuscito: %s", ex)
            return {"ok": False, "error": "Il sito non risponde, riprova tra poco"}
        user = page_user(props)
        if not user:
            return {"ok": False, "error": login_error(props) or "Accesso non riuscito"}
        try:
            self._clear_chrome_cookies()
            for c in jar:
                params = {"name": c.name, "value": c.value, "url": BASE_URL + (c.path or "/"),
                          "secure": bool(c.secure), "path": c.path or "/",
                          "httpOnly": c.has_nonstandard_attr("HttpOnly") or c.name != "XSRF-TOKEN"}
                if c.domain_specified:
                    params["domain"] = c.domain
                if c.expires:
                    params["expires"] = c.expires
                self.cdp.call("Network.setCookie", params)
        except Exception as ex:
            log.warning("sc: cookie non copiati in Chrome: %s", ex)
            return {"ok": False, "error": "Accesso riuscito, ma Chrome non ha salvato la sessione"}
        log.info("sc: accesso riuscito")
        return dict(self._set_state(True, user), ok=True)

    def _clear_chrome_cookies(self):
        for c in self._chrome_cookies():
            self.cdp.call("Network.deleteCookies", {"name": c["name"], "domain": c["domain"],
                                                    "path": c.get("path", "/")})

    def after_login(self):
        return self.login_state(fresh=True)

    def logout(self):
        """Esce dall'account: via i cookie del sito da Chrome."""
        try:
            self._clear_chrome_cookies()
        except Exception as ex:
            log.warning("sc: uscita: %s", ex)
        return self._set_state(False)

    def _get(self, key, url, ttl):
        """Cache TTL single-flight con fallback all'ultimo dato disponibile.

        Se più thread chiedono la stessa chiave, uno solo effettua il download.
        Gli altri attendono e poi rileggono la cache aggiornata.
        """
        if not url:
            return {}

        # Crea/recupera il lock della chiave sotto il lock globale.
        with self.lock:
            key_lock = self._key_locks.get(key)
            if key_lock is None:
                key_lock = threading.Lock()
                self._key_locks[key] = key_lock

        with key_lock:
            # Ricontrollo obbligatorio: un altro thread potrebbe aver scaricato
            # il dato mentre questo thread aspettava il lock.
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
                # Mantiene lo stale-if-error: se il server fallisce,
                # restituisce l'ultima copia disponibile, anche se scaduta.
                with self.lock:
                    cached = self.cache.get(key)
                return cached[1] if cached else {}

            with self.lock:
                self.cache[key] = (time.monotonic(), data)

            return data

    def _load_genre_rail(self, genre):
        """Le righe di un genere: una per i film e/o una per le serie (GENRES dice quali),
        ognuna con i titoli più visti di quel tipo."""
        genre_id, genre_name, genre_type = genre
        rails = []
        for kind, page in (("movie", "films"), ("tv", "series")):
            if genre_type not in (kind, "all"):
                continue
            data = self._get(f"genere:{genre_id}:{kind}", genre_url(genre_id, kind), RAIL_TTL)
            items = [x for x in map(parse_series, genre_entries(data))
                     if x["id"] and x["title"] and x["poster"]
                     and (x["category"] == "Film") == (kind == "movie")]
            if items:
                rails.append({"id": f"genere-{'film' if kind == 'movie' else 'serie'}:{genre_id}",
                              "page": page, "title": genre_name, "items": items})
        return rails

    # ---------- righe: GET /api/sc?page=home|series|films ----------
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

        threading.Thread(target=run, name="sc-generi", daemon=True).start()

    def search(self, query):
        """Ricerca globale per nome su StreamingUnity."""
        query = _s(query)[:100]
        if not query:
            return {"query": "", "items": []}

        try:
            client = self._client()
            if client is None:
                raise RuntimeError(
                    self._api_error or "scuapi non disponibile"
                )

            results = client.search(query)

            # SCAPI restituisce normalmente un dizionario di risultati.
            entries = list(results.values()) if isinstance(results, dict) else _l(results)

            items = []
            seen = set()

            for entry in entries:
                item = parse_series(entry)

                if not item["id"] or not item["title"] or not item["poster"]:
                    continue

                if item["id"] in seen:
                    continue

                seen.add(item["id"])
                items.append(item)

            return {"query": query, "items": items}

        except Exception as ex:
            log.warning("%s ricerca '%s': %s", NAME, query, ex)
            return {
                "query": query,
                "items": [],
                "error": "Ricerca temporaneamente non disponibile",
            }

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

            prefs_history = self.prefs.get("sc_history") or []
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
            for h in (self.prefs.get("sc_history") or [])
        ]

    def play_target(self, url):
        """Cosa aprire a schermo per l'episodio url: (indirizzo, provenienza). Il player da solo;
        se non si trova, la pagina dell'episodio come prima."""
        try:
            return resolve_episode(url)
        except Exception as ex:
            log.warning("%s: player di %s non trovato, apro la pagina: %s", NAME, url, ex)
            return url, None

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
            "sc_history",
            lambda items: (
                [h] + [
                    x for x in items
                    if x.get("series") != h["series"]
                ]
            )[:HISTORY_MAX],
        )

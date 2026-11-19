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
import http.cookiejar
import threading
import time
import urllib.parse
import urllib.request

from .util import DESKTOP_UA, log

NAME = "au"

# ======================================================================================
# 1. IL CONNETTORE — da scrivere
# ======================================================================================

SITE_HOST = ""                      # TODO: es. "www.animeunity.so" (senza https://)
BASE_URL = f"https://{SITE_HOST}"
EPISODE_PATH = "/"                  # TODO: inizio dell'indirizzo delle pagine episodio, es. "/anime/"

# ---------- accesso ----------
LOGIN_REQUIRED = True               # senza accesso la sezione mostra solo la schermata di accesso
                                    # (False mentre scrivi il catalogo, se vuoi provarlo senza account)
SESSION_COOKIES = ()                # TODO: nomi (o inizi, con "_" finale) dei cookie che il sito
                                    # crea dopo l'accesso, es. ("animeunity_session", "remember_web_")
LOGIN_STATUS_TTL = 300              # lo stato si ricontrolla al massimo ogni 5 minuti

# ---------- cache ----------
RAIL_TTL = 1800                     # righe: 30 minuti
SERIES_TTL = 900                    # un anime con gli episodi: 15 minuti
HISTORY_MAX = 12                    # titoli in "Continua a guardare"


def serie(id, title, poster="", hero="", logo="", desc="", genres=(), seasons=None, current=None,
          category="Anime"):
    """Un anime nel formato del launcher. seasons: [(id, numero, titolo), ...] o None = una sola."""
    ss = [{"id": str(s[0]), "n": int(s[1]), "title": str(s[2])} for s in (seasons or [("1", 1, "Episodi")])]
    return {"id": str(id), "title": title or "", "poster": poster or "", "hero": hero or poster or "",
            "logo": logo or "", "desc": desc or "", "category": category, "genres": list(genres)[:3],
            "seasons": ss, "current": str(current) if current is not None else ss[-1]["id"]}


def episodio(id, url, title="", n=None, desc="", dur=0, date=0, image=""):
    """Un episodio nel formato del launcher (dur in secondi, date in millisecondi)."""
    return {"id": str(id), "url": url, "title": title or (f"Episodio {n}" if n is not None else "Episodio"),
            "n": n, "desc": desc or "", "dur": int(dur or 0), "date": int(date or 0),
            "channel": "", "image": image or ""}


def is_episode_url(u):
    """Solo pagine episodio HTTPS del sito: tvbox apre a schermo intero solo queste."""
    p = urllib.parse.urlparse(u or "")
    return bool(SITE_HOST) and p.scheme == "https" and p.hostname == SITE_HOST and p.path.startswith(EPISODE_PATH)


def fetch_home():
    """Righe della scheda HOME (es. "In evidenza", "Ultimi episodi", "Popolari"):
    [riga, ...]. "Continua a guardare" la aggiunge tvbox in cima da sola."""
    raise NotImplementedError("fetch_home")


def fetch_anime():
    """Righe della scheda ANIME (es. una per genere): [riga, ...]."""
    raise NotImplementedError("fetch_anime")


def fetch_search(query):
    """Ricerca per nome: [serie, ...]."""
    raise NotImplementedError("fetch_search")


def fetch_series(sid, season=None):
    """Un anime e gli episodi della stagione scelta (season = id della stagione, o None per
    quella di partenza): (serie, [episodio, ...]). Gli episodi in ordine dal più recente."""
    raise NotImplementedError("fetch_series")


def site_login(opener, jar, username, password):
    """Accesso al sito con utente e password, come il modulo di login del browser.
    opener: urllib con i cookie in jar (usalo per tutte le richieste: GET della pagina di login
    per il token, POST del modulo). Restituisci {"ok": True, "user": "nome"} oppure
    {"ok": False, "error": "messaggio per la TV"}. I cookie rimasti in jar li copia tvbox in
    Chrome, dove li usa il player del sito. Esempio completo: SC.login in tvbox/sc.py."""
    raise NotImplementedError("site_login")


def site_user(cookie_header):
    """Facoltativo: chi è collegato con questi cookie ("Cookie: ..." già pronto)? Il nome,
    oppure None se il sito dice che non si è collegati. Se resta NotImplementedError, basta la
    presenza dei cookie di SESSION_COOKIES in Chrome."""
    raise NotImplementedError("site_user")


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
                items = [x for x in r.get("items") or [] if x.get("id") and x.get("title")]
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
            items = [x for x in fetch_search(query) or [] if x.get("id") and x.get("title")]
            return {"query": query, "items": items}
        except NotImplementedError:
            return {"query": query, "items": [], "error": TODO_MSG}
        except Exception as ex:
            log.warning("AnimeUnity ricerca '%s': %s", query, ex)
            return {"query": query, "items": [], "error": "Ricerca temporaneamente non disponibile"}

    # ---------- un anime: GET /api/au?action=series&id=...&season=... ----------
    def series(self, sid, season=None):
        try:
            s, eps = self._cached(f"serie:{sid}:{season}", SERIES_TTL, lambda: fetch_series(sid, season))
        except NotImplementedError:
            return {"error": TODO_MSG, "login": self.login_state()}
        except Exception:
            return {"error": "Non disponibile", "login": self.login_state()}
        eps = [e for e in eps or [] if is_episode_url(e.get("url"))]
        last = next((h for h in self.prefs.get("au_history") if h.get("series") == str(sid)), None)
        return dict(s, season=str(season) if season else s.get("current"), episodes=eps,
                    last=last.get("episode") if last else None)

    # ---------- Continua a guardare ----------
    def history(self):
        return [{"id": h["series"], "title": h["title"], "poster": h["poster"], "hero": h.get("hero", ""),
                 "logo": h.get("logo", ""), "desc": h.get("ep", ""),
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
        st = {"available": True, "required": LOGIN_REQUIRED, "logged": bool(logged), "user": user or ""}
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

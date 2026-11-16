"""IL MIO CATALOGO — scheletro vuoto di un connettore, sul modello di mediaset.py.

Tutto il resto è già collegato (API, pagine del launcher, apertura a tutto schermo, MENU che
torna alla serie, "Continua a guardare"): qui va scritto SOLO come si leggono i dati del tuo sito.
Finché RAILS è vuoto la sezione mostra "Nessun contenuto": la TV non si rompe.

Il percorso, dal telecomando al video:

    launcher/js/mio.js ──GET /api/mio──────────────────► Mio.rails()     righe di locandine
                       ──GET /api/mio?action=series───► Mio.series()    una serie: stagioni ed episodi
                       ──GET /api/mio?action=play─────► is_episode_url() + Mio.remember()
                                                         poi tvd apre l'url dell'episodio a tutto
                                                         schermo (Session.episode, tvbox/session.py)
                       ──GET /api/mio?action=login────► tvd apre LOGIN_URL sul televisore
                       ──GET /api/mio?action=logout───► Mio.logout()

L'ACCESSO (login) si fa sul sito vero, dentro il Chrome della TV, con la navigazione assistita
e la tastiera a schermo, come per qualsiasi sito: niente password nel codice o nei file di tvbox.
    1. nella sezione c'è il pulsante "Accedi" (in alto a destra) se LOGIN_URL non è vuoto;
    2. OK → si apre LOGIN_URL a schermo; l'utente entra con le sue credenziali;
    3. MENU (o HOME) → si torna alla sezione. Chrome tiene i cookie del sito nel suo profilo,
       quindi l'accesso resta anche dopo uno spegnimento, finché il sito non lo fa scadere;
    4. tvd legge quei cookie da Chrome (DevTools Protocol, Network.getCookies) e li manda con
       le richieste del catalogo (auth_headers); i video si aprono nello stesso Chrome, quindi
       sono già collegati anche loro;
    5. se il sito tiene il "token" in localStorage invece che nei cookie: TOKEN_JS lo legge dalla
       pagina del sito quando l'utente torna indietro (salvato in ~/.config/tvbox/mio-token.json,
       leggibile solo dall'utente tv).
Cookie e token si vedono in Chrome: Strumenti per sviluppatori → Application → Cookies /
Local Storage, sul sito, da collegati. Nella scheda Network, una richiesta del catalogo mostra
quale intestazione serve (Cookie: …  oppure  Authorization: Bearer …).

Cosa ti serve dal sito (di solito si trova con gli Strumenti per sviluppatori di Chrome →
Rete/Network → filtro "Fetch/XHR", mentre navighi il sito):
    1. un indirizzo che dà un ELENCO di titoli (per categoria, genere, "più visti"…)   → rails()
    2. un indirizzo che dà UN titolo con le sue stagioni                               → series()
    3. un indirizzo che dà gli EPISODI di una stagione                                 → series()
    4. per ogni episodio, l'indirizzo della PAGINA del sito dove si guarda (con il suo player):
       la TV apre quella pagina, avvia il video e lo mette a tutto schermo da sola.

Regole da rispettare:
    - le funzioni parse_* lavorano su dati già scaricati (niente rete): così si provano con i
      test in tests/test_core.py, come quelle di Mediaset;
    - la rete passa sempre da self._get() (cache + nessun errore che arriva al launcher);
    - le immagini sono indirizzi https completi; le durate in SECONDI, le date in MILLISECONDI
      dal 1970 (come Date.now() in JavaScript);
    - mai lanciare eccezioni verso l'API: in caso di problemi restituisci liste vuote o
      {"error": "testo da mostrare"}.
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from .util import DESKTOP_UA, USER_DIR, log

NAME = "Il mio catalogo"         # TODO: il nome del tuo servizio (compare nei log)

# TODO: il sito dei video. Solo gli url con questo host si possono aprire dalla sezione
# (protezione: il launcher non può far aprire indirizzi qualsiasi). Es. "www.esempio.it".
SITE_HOST = ""
# TODO: la parte iniziale del percorso delle pagine degli episodi. Es. "/video/". "" = tutte.
EPISODE_PATH = ""

# TODO: le righe della sezione: (id, titolo mostrato sopra la riga, parametro tuo).
# Il "parametro tuo" è quello che serve per costruire l'indirizzo dell'elenco: una categoria,
# un genere, un id di playlist… Es. ("film", "Film", "category:film").
RAILS = []

# ---------- accesso (login) ----------
# TODO: pagina di accesso del sito, es. "https://www.esempio.it/login". "" = il sito non chiede
# l'accesso: il pulsante "Accedi" non compare e tutto il resto del login resta spento.
LOGIN_URL = ""
# TODO: True = senza accesso il catalogo non si carica (si vede solo "Accedi per vedere il catalogo").
LOGIN_REQUIRED = False
# TODO: siti di cui leggere i cookie (quelli a cui vanno le richieste del catalogo), es.
# ["https://www.esempio.it/", "https://api.esempio.it/"]. Vuoto = solo https://SITE_HOST/
COOKIE_URLS = []
# TODO: nome di un cookie che c'è SOLO quando si è collegati (es. "session_id", "access_token").
LOGIN_COOKIE = ""
# TODO (facoltativo): espressione JavaScript che sulla pagina del sito restituisce il token, se
# il sito non usa i cookie. Es. "localStorage.getItem('authToken')" oppure
# "JSON.parse(localStorage.getItem('user') || '{}').token". "" = non serve.
TOKEN_JS = ""

RAIL_TTL = 1800                  # elenchi: si riscaricano dopo 30 minuti
SERIES_TTL = 1800                # una serie (stagioni)
EPISODES_TTL = 900               # episodi di una stagione: 15 minuti
HISTORY_MAX = 12                 # voci di "Continua a guardare"


# ====================================================================================
#  DA SCRIVERE: dai dati del sito alle forme che si aspetta il launcher
# ====================================================================================

def is_logged_in(auth):
    """TODO se serve: siamo collegati? auth = {"cookies": {nome: valore}, "token": str | None}
    (cookie letti da Chrome per COOKIE_URLS, token letto con TOKEN_JS)."""
    return bool((LOGIN_COOKIE and auth["cookies"].get(LOGIN_COOKIE)) or auth["token"])


def auth_headers(auth):
    """TODO se serve: intestazioni da aggiungere alle richieste del catalogo (rail_url,
    series_url, episodes_url). Di base: tutti i cookie, e il token come "Bearer".
    Alcuni siti vogliono altro, es. {"x-api-key": "...", "Authorization": auth["token"]}."""
    h = {}
    if auth["cookies"]:
        h["Cookie"] = "; ".join(f"{k}={v}" for k, v in auth["cookies"].items())
    if auth["token"]:
        h["Authorization"] = "Bearer " + auth["token"]
    return h


def rail_url(param):
    """TODO: indirizzo dell'ELENCO di titoli per una riga (param = terzo campo di RAILS).
    Es. return "https://api.esempio.it/titoli?categoria=" + urllib.parse.quote(param)"""
    return ""


def rail_entries(data):
    """TODO: dalla risposta di rail_url() alla lista dei titoli grezzi (uno per locandina).
    Es. return data.get("items") or []"""
    return []


def series_url(sid):
    """TODO: indirizzo di UN titolo, con le sue stagioni (sid = "id" restituito da parse_series)."""
    return ""


def series_entry(data):
    """TODO: dalla risposta di series_url() al titolo grezzo (lo stesso formato che legge
    parse_series), oppure None se non c'è. Es. return (data.get("items") or [None])[0]"""
    return None


def episodes_url(series, season):
    """TODO: indirizzo degli EPISODI di una stagione.
    series = risultato di parse_series; season = una voce di series["seasons"]."""
    return ""


def episode_entries(data):
    """TODO: dalla risposta di episodes_url() alla lista degli episodi grezzi."""
    return []


def parse_series(e):
    """TODO: un titolo del sito → una locandina / una serie. Chiavi che il launcher usa:

        id        str   OBBLIGATORIO  identificativo stabile (torna in series(id) e nella cronologia)
        title     str   OBBLIGATORIO  nome
        poster    str   OBBLIGATORIO  immagine VERTICALE 2:3 (circa 264x396): la locandina della riga
        hero      str   facoltativo   immagine ORIZZONTALE 16:9 grande: sfondo in alto e nella serie
        logo      str   facoltativo   logo del titolo (PNG trasparente): se c'è, sostituisce il nome
        desc      str   facoltativo   trama (in alto, 3 righe; nella serie, 8 righe)
        category  str   facoltativo   es. "Serie TV"     } mostrati come "Serie TV · Giallo · Commedia"
        genres    [str] facoltativo   es. ["Giallo"]     }
        seasons   [ {"id": str, "n": int, "title": str} ]  dalla prima all'ultima; OBBLIGATORIO
                  almeno una (un film o un programma senza stagioni: una sola, n = 1)
        current   str   facoltativo   id della stagione da mostrare per prima (se no: l'ultima)
    """
    return {"id": "", "title": "", "poster": "", "hero": "", "logo": "", "desc": "",
            "category": "", "genres": [], "seasons": [], "current": None}


def parse_episode(e):
    """TODO: un episodio del sito → una riga della lista episodi. Chiavi:

        id       str        OBBLIGATORIO  identificativo stabile (segna "ULTIMO VISTO")
        url      str        OBBLIGATORIO  pagina del sito dove si guarda: https://SITE_HOST/...
        title    str        OBBLIGATORIO  es. "Episodio 3 - Il ritorno"
        n        int|None   numero dell'episodio (None se non numerato)
        desc     str        trama breve
        dur      int        durata in secondi (0 = non mostrata)
        date     int        data di pubblicazione in millisecondi (0 = non mostrata)
        channel  str        es. il canale di provenienza (vuoto = non mostrato)
        image    str        fermo immagine 16:9 piccolo (circa 360x203)
    """
    return {"id": "", "url": "", "title": "", "n": None, "desc": "", "dur": 0, "date": 0,
            "channel": "", "image": ""}


def episodes_of(entries):
    """Episodi da mostrare, nell'ordine della lista (in cima il più recente). Qui si tolgono
    quelli che non si possono guardare (a pagamento, clip, senza indirizzo…). TODO se serve."""
    eps = [x for x in (parse_episode(e) for e in entries) if x["url"]]
    return sorted(eps, key=lambda x: (x["n"] if x["n"] is not None else -1, x["date"]), reverse=True)


# ====================================================================================
#  GIÀ PRONTO: non dovrebbe servire toccarlo
# ====================================================================================

def is_episode_url(u):
    """Solo pagine del tuo sito, in https (vedi SITE_HOST / EPISODE_PATH)."""
    p = urllib.parse.urlparse(u or "")
    return bool(SITE_HOST) and p.scheme == "https" and p.hostname == SITE_HOST \
        and p.path.startswith(EPISODE_PATH or "/")


def pick_season(s, season=None):
    """La stagione da mostrare: quella chiesta, altrimenti quella "current", altrimenti l'ultima."""
    return next((x for x in s["seasons"] if season and x["id"] == season), None) \
        or next((x for x in s["seasons"] if x["id"] == s.get("current")), None) or s["seasons"][-1]


TOKEN_FILE = os.path.join(USER_DIR, "mio-token.json")
AUTH_TTL = 30                    # i cookie si rileggono da Chrome al massimo ogni 30 secondi


def get_json_auth(url, headers, timeout=12):
    """Come util.get_json, ma con l'identità di Chrome e le intestazioni dell'accesso."""
    req = urllib.request.Request(url, headers=dict({"User-Agent": DESKTOP_UA, "Accept": "application/json"},
                                                   **headers))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class Mio:
    def __init__(self, prefs, cdp=None):
        self.prefs = prefs
        self.cdp = cdp                      # Chrome: da qui si leggono i cookie del sito
        self.lock = threading.Lock()
        self.cache = {}                     # chiave -> (istante, dati)
        self._auth = (0.0, {"cookies": {}, "token": None})
        self._logged = None                 # ultimo stato visto: se cambia, via la cache

    # ---------- accesso ----------
    def _cookie_urls(self):
        return COOKIE_URLS or ([f"https://{SITE_HOST}/"] if SITE_HOST else [])

    def auth(self, fresh=False):
        """{"cookies": {nome: valore}, "token": str | None}, dai cookie di Chrome e dal token salvato."""
        t, a = self._auth
        if not fresh and time.monotonic() - t < AUTH_TTL:
            return a
        a = {"cookies": {}, "token": None}
        urls = self._cookie_urls()
        if LOGIN_URL and urls and self.cdp:
            try:
                a["cookies"] = {c["name"]: c["value"]
                                for c in self.cdp.call("Network.getCookies", {"urls": urls}).get("cookies", [])}
            except Exception as ex:
                log.debug("%s cookie non letti: %s", NAME, ex)
        if LOGIN_URL and TOKEN_JS:
            try:
                with open(TOKEN_FILE, encoding="utf-8") as f:
                    a["token"] = json.load(f).get("token") or None
            except (OSError, ValueError):
                pass
        self._auth = (time.monotonic(), a)
        logged = bool(LOGIN_URL) and is_logged_in(a)
        if logged != self._logged:                       # collegato / scollegato: dati diversi
            self._logged = logged
            with self.lock:
                self.cache.clear()
        return a

    def login_state(self, fresh=False):
        """Per il launcher: {"available": c'è un login, "logged": collegati, "required": serve}."""
        if not LOGIN_URL:
            return {"available": False, "logged": False, "required": False}
        try:
            logged = is_logged_in(self.auth(fresh))
        except Exception as ex:
            log.warning("%s stato dell'accesso: %s", NAME, ex)
            logged = False
        return {"available": True, "logged": logged, "required": LOGIN_REQUIRED}

    def after_login(self):
        """Chiamata da tvd quando l'utente lascia la pagina di accesso (MENU o HOME), con la
        pagina del sito ancora aperta: legge il token (TOKEN_JS) e rilegge i cookie."""
        if TOKEN_JS and self.cdp:
            try:
                tok = self.cdp.eval(f"(() => {{ try {{ return {TOKEN_JS}; }} catch (e) {{ return null; }} }})()",
                                    timeout=4)
                if isinstance(tok, str) and tok:
                    os.makedirs(USER_DIR, exist_ok=True)
                    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump({"token": tok, "t": int(time.time())}, f)
            except Exception as ex:
                log.warning("%s token non letto: %s", NAME, ex)
        log.info("%s: accesso %s", NAME, "riuscito" if self.login_state(fresh=True)["logged"] else "non riuscito")

    def logout(self):
        """Esce: cancella da Chrome i cookie del sito e il token salvato."""
        urls = self._cookie_urls()
        if self.cdp and urls:
            try:
                for c in self.cdp.call("Network.getCookies", {"urls": urls}).get("cookies", []):
                    self.cdp.call("Network.deleteCookies", {"name": c["name"], "domain": c["domain"],
                                                            "path": c.get("path", "/")})
            except Exception as ex:
                log.warning("%s uscita: %s", NAME, ex)
        try:
            os.remove(TOKEN_FILE)
        except OSError:
            pass
        return self.login_state(fresh=True)

    # ---------- rete ----------
    def _get(self, key, url, ttl):
        """Scarica JSON con cache (e con l'accesso, se c'è); se il sito non risponde usa
        l'ultima copia (o {})."""
        if not url:
            return {}
        headers = auth_headers(self.auth()) if LOGIN_URL else {}
        with self.lock:
            c = self.cache.get(key)
            if c and time.monotonic() - c[0] < ttl:
                return c[1]
        try:
            d = get_json_auth(url, headers)
        except Exception as ex:
            log.warning("%s %s non disponibile: %s", NAME, key, ex)
            return c[1] if c else {}
        with self.lock:
            self.cache[key] = (time.monotonic(), d)
        return d

    # ---------- righe della sezione: GET /api/mio ----------
    def rails(self):
        """→ {"rails": [{"id", "title", "items": [locandina, ...]}, ...], "login": login_state()}"""
        login = self.login_state()
        if login["required"] and not login["logged"]:
            return {"rails": [], "login": login}
        out = []
        hist = self.history()
        if hist:
            out.append({"id": "continua", "title": "Continua a guardare", "items": hist})
        for rid, title, param in RAILS:
            try:
                ents = rail_entries(self._get("rail:" + rid, rail_url(param), RAIL_TTL))
                items = [parse_series(e) for e in ents]
            except Exception as ex:                      # un parse sbagliato non blocca le altre righe
                log.warning("%s riga %s: %s", NAME, rid, ex)
                items = []
            out.append({"id": rid, "title": title,
                        "items": [x for x in items if x["id"] and x["poster"] and x["seasons"]]})
        return {"rails": out, "login": login}

    # ---------- una serie: GET /api/mio?action=series&id=...&season=... ----------
    def series(self, sid, season=None):
        """→ la serie di parse_series, più:
              season    id della stagione mostrata
              episodes  [episodio di parse_episode, ...]
              last      id dell'ultimo episodio aperto (o None)"""
        login = self.login_state()
        if login["required"] and not login["logged"]:
            return {"error": "Accedi per vedere questo titolo", "login": login}
        try:
            e = series_entry(self._get("serie:" + sid, series_url(sid), SERIES_TTL))
            if not e:
                return {"error": "Titolo non trovato"}
            s = parse_series(e)
            if not s["seasons"]:
                return dict(s, episodes=[], season=None, last=None)
            pick = pick_season(s, season)
            eps = episodes_of(episode_entries(
                self._get("eps:" + sid + ":" + pick["id"], episodes_url(s, pick), EPISODES_TTL)))
        except Exception as ex:
            log.warning("%s serie %s: %s", NAME, sid, ex)
            return {"error": "Non disponibile"}
        last = next((h for h in self.prefs.get("mio_history") if h["series"] == sid), None)
        return dict(s, season=pick["id"], episodes=eps, last=last["episode"] if last else None)

    # ---------- Continua a guardare (in prefs.json, chiave mio_history) ----------
    def history(self):
        return [{"id": h["series"], "title": h["title"], "poster": h["poster"], "hero": h.get("hero", ""),
                 "logo": h.get("logo", ""), "desc": h.get("ep", ""),
                 "sub": h.get("ep") or (f"Ep. {h['n']}" if h.get("n") is not None else ""), "episode": h["episode"]}
                for h in self.prefs.get("mio_history")]

    def remember(self, q):
        """Ricorda l'episodio aperto (in cima a "Continua a guardare", una voce per serie)."""
        h = {"series": q.get("series", ""), "title": (q.get("title") or "")[:60],
             "poster": q.get("poster", ""), "hero": q.get("hero", ""), "logo": q.get("logo", ""),
             "ep": (q.get("ep") or "")[:60], "episode": q.get("episode", ""),
             "n": int(q["n"]) if (q.get("n") or "").isdigit() else None, "t": int(time.time())}
        if not h["series"]:
            return
        self.prefs.update("mio_history", lambda l: ([h] + [x for x in l if x["series"] != h["series"]])[:HISTORY_MAX])

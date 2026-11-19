"""Catalogo Mediaset Infinity (fiction, serie, programmi, cartoni…) per la sezione Mediaset della TV.

I dati vengono dai feed pubblici usati anche dal sito (nessun account):
    serie     .../mediaset-prod-all-series-v2     categoria, locandine, stagioni, pagina
    episodi   .../mediaset-prod-all-programs-v2   per stagione: numero, titolo, durata, video

Il video si guarda sulla pagina dell'episodio del sito (con il suo player e la licenza),
aperta da tvd a tutto schermo. La TV ricorda gli ultimi episodi aperti ("Continua a guardare").
Le funzioni parse_* lavorano sui dati già scaricati: si provano con i test.
"""
import json
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from .cdp import HiddenTab
from .util import get_json, log

FEED = "https://feed.entertainment.tv.theplatform.eu/f/PR1GhC/"
SERIES_FIELDS = ("guid,title,description,thumbnails,seriesTvSeasons,tags,updated,"
                 "mediasetprogram$pageUrl,mediasetprogram$currentSeason,mediasetprogram$genres")

# righe della sezione: (id, titolo, categoria nel catalogo Mediaset). Fuori: "Sport" (quasi solo
# clip) e "Microdrama" (video verticali per il telefono).
RAILS = [("fiction", "Fiction e soap in onda", "Fiction"), ("serie", "Serie TV", "Serie TV"),
         ("programmi", "Programmi TV", "Intrattenimento"), ("cartoni", "Cartoni", "Cartoni"),
         ("documentari", "Documentari", "Documentari"), ("informazione", "Approfondimento", "Informazione")]
FULL_MIN_S = 20 * 60          # programmi senza numeri di puntata: si tengono i video da 20 minuti in su
PLAYABLE_TTL = 6 * 3600       # "questo titolo ha qualcosa di gratuito da vedere?": valido 6 ore
CHECK_FIELDS = ("guid,tvSeasonEpisodeNumber,mediasetprogram$duration,mediasetprogram$videoPageUrl,"
                "mediasetprogram$channelsRights")
HISTORY_MAX = 12

# ---------- accesso (login) ----------
# Il sito usa Gigya (SAP, servito da login.mediaset.it). L'accesso lo fa tvd: apre la pagina di
# Mediaset in una scheda nascosta del Chrome della TV (cdp.HiddenTab) e chiama la funzione di
# accesso della libreria del sito (gigya.accounts.login) con email e password scritte nella
# schermata di tvbox. Cookie e sessione li imposta la libreria, come accedendo a mano; la
# password non si salva. Se Gigya chiede il captcha, l'accesso si fa una volta sul sito.
SITE = "https://mediasetinfinity.mediaset.it/"
GIGYA_WAIT = 40               # secondi per avere la libreria pronta (la pagina è pesante)
GIGYA_READY = "!!(window.gigya && gigya.accounts && gigya.accounts.login)"
LOGIN_ERRORS = {403042: "Email o password non corretti", 403043: "Email o password non corretti",
                403120: "Account bloccato per troppi tentativi: riprova tra qualche minuto",
                403041: "Account disattivato", 401030: "Email o password non corretti"}
NEEDS_SITE = {401020, 401021, 206001, 206002, 206006}   # captcha, dati da completare: sul sito


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
            "logo": _img(th, "logo_horizontal-320x128"),          # logo della serie (al posto del titolo)
            "genres": [g for g in (e.get("mediasetprogram$genres") or []) if isinstance(g, str)][:3],
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
    """Solo episodi veri e gratuiti, dal più recente: quelli con il numero; se un programma non
    numera le puntate (talk show, programmi quotidiani), i video lunghi per data (le clip no)."""
    eps = [x for x in (parse_episode(e) for e in entries) if x["url"] and x["free"]]
    num = [x for x in eps if x["n"] is not None]
    if num:
        return sorted(num, key=lambda x: (x["n"], x["date"]), reverse=True)   # numeri doppi: conta la data
    return sorted((x for x in eps if x["dur"] >= FULL_MIN_S), key=lambda x: x["date"], reverse=True)


def is_episode_url(u):
    p = urllib.parse.urlparse(u or "")
    return p.scheme == "https" and p.hostname == "mediasetinfinity.mediaset.it" and p.path.startswith("/video/")


def pick_season(s, season=None):
    """La stagione da mostrare: quella chiesta, altrimenti quella in corso, altrimenti l'ultima."""
    return next((x for x in s["seasons"] if season and (x["guid"] == season or x["id"] == season)), None) \
        or next((x for x in s["seasons"] if x["guid"] == s["current"]), None) or s["seasons"][-1]


def gigya_login_js(email, password):
    """Espressione JS: accesso con Gigya; restituisce {errorCode, errorMessage, email}."""
    args = json.dumps({"loginID": email, "password": password, "sessionExpiration": -2})
    return ("new Promise(r => gigya.accounts.login(Object.assign(" + args + ", {callback: x => r({"
            "errorCode: x.errorCode, errorMessage: x.errorMessage || '', "
            "email: (x.profile && x.profile.email) || ''})})))")


def login_message(code, msg=""):
    return LOGIN_ERRORS.get(code) or (f"Accesso non riuscito ({msg or code})")


class Mediaset:
    def __init__(self, prefs, cdp=None):
        self.prefs = prefs
        self.cdp = cdp                      # Chrome della TV: cookie e scheda nascosta per l'accesso
        self.lock = threading.Lock()
        self.cache = {}                     # chiave -> (istante, dati)
        self.playable_cache = {}            # stagione -> (istante, True/False)
        self.checking = threading.Lock()    # un solo controllo dei titoli alla volta

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
        def rail(r):
            rid, title, cat = r
            url = (FEED + "mediaset-prod-all-series-v2?byTags=" + urllib.parse.quote("category:" + cat) +
                   "&sort=updated%7Cdesc&range=1-30&fields=" + urllib.parse.quote(SERIES_FIELDS, safe=","))
            items = [parse_series(e) for e in self._get("rail:" + rid, url, 1800).get("entries") or []]
            return {"id": rid, "title": title, "items": [x for x in items if x["poster"] and x["seasons"]]}
        with ThreadPoolExecutor(max_workers=3) as pool:          # le righe si scaricano insieme
            rails = list(pool.map(rail, RAILS))
        # via i titoli senza niente di gratuito da vedere (a pagamento, solo clip); quelli non
        # ancora controllati restano e vengono controllati in sottofondo
        unknown = []
        for r in rails:
            r["items"] = [x for x in r["items"] if self.known(x) is not False]
            unknown += [x for x in r["items"] if self.known(x) is None]
        if unknown:
            threading.Thread(target=self.check, args=(unknown,), daemon=True).start()
        return {"rails": out + rails}

    # ---------- titoli con qualcosa da vedere ----------
    def known(self, s):
        """True / False se già controllato (da meno di 6 ore), None se non si sa ancora."""
        c = self.playable_cache.get(pick_season(s)["id"])
        return c[1] if c and time.monotonic() - c[0] < PLAYABLE_TTL else None

    def playable(self, s):
        """Ha puntate gratuite da guardare? (solo numero e durata dei video gratuiti: risposta piccola)"""
        sid = pick_season(s)["id"]
        url = (FEED + "mediaset-prod-all-programs-v2?byTvSeasonId=" + urllib.parse.quote(sid, safe="") +
               "&byCustomValue=" + urllib.parse.quote("{mediasetprogram$channelsRights}{AVOD}") +
               "&range=1-120&fields=" + urllib.parse.quote(CHECK_FIELDS, safe=","))
        try:
            ok = bool(episodes_of(get_json(url, timeout=12).get("entries") or []))
        except Exception as ex:
            log.debug("Mediaset controllo %s: %s", s.get("title"), ex)
            return None
        self.playable_cache[sid] = (time.monotonic(), ok)
        return ok

    def check(self, items, wait=False):
        if not self.checking.acquire(blocking=wait):          # c'è già un controllo in corso
            return
        try:
            todo = [x for x in items if self.known(x) is None]
            with ThreadPoolExecutor(max_workers=3) as pool:
                res = list(pool.map(self.playable, todo))
            log.info("Mediaset: controllati %d titoli, %d senza niente di gratuito", len(todo), res.count(False))
        finally:
            self.checking.release()

    def prewarm(self, delay=60):
        """Dopo l'accensione, in sottofondo: catalogo e controllo dei titoli già pronti quando
        si apre la sezione Mediaset."""
        time.sleep(delay)
        try:
            r = self.rails()["rails"]
            self.check([x for rail in r for x in rail["items"] if rail["id"] != "continua"], wait=True)
        except Exception as ex:
            log.warning("Mediaset in anticipo: %s", ex)

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
        pick = pick_season(s, season)
        url = (FEED + "mediaset-prod-all-programs-v2?byTvSeasonId=" + urllib.parse.quote(pick["id"], safe="") +
               "&sort=tvSeasonEpisodeNumber%7Cdesc&range=1-120")
        eps = episodes_of(self._get("eps:" + pick["id"], url, 900).get("entries") or [])
        last = next((h for h in self.prefs.get("ms_history") if h["series"] == guid), None)
        return dict(s, season=pick["guid"], episodes=eps, last=last["episode"] if last else None)

    # ---------- Continua a guardare ----------
    def history(self):
        return [{"id": h["series"], "title": h["title"], "poster": h["poster"], "hero": h.get("hero", ""),
                 "logo": h.get("logo", ""), "desc": h.get("ep", ""),
                 "sub": h.get("ep") or (f"Ep. {h['n']}" if h.get("n") is not None else ""), "episode": h["episode"]}
                for h in self.prefs.get("ms_history")]

    def remember(self, q):
        """Ricorda l'episodio aperto (in cima a "Continua a guardare", una voce per serie)."""
        h = {"series": q.get("series", ""), "title": (q.get("title") or "")[:60],
             "poster": q.get("poster", ""), "hero": q.get("hero", ""), "logo": q.get("logo", ""),
             "ep": (q.get("ep") or "")[:60], "episode": q.get("episode", ""),
             "n": int(q["n"]) if (q.get("n") or "").isdigit() else None, "t": int(time.time())}
        if not h["series"]:
            return
        self.prefs.update("ms_history", lambda l: ([h] + [x for x in l if x["series"] != h["series"]])[:HISTORY_MAX])

    # ---------- accesso: GET /api/mediaset?action=status|login|logout ----------
    def _cookies(self):
        if not self.cdp:
            return []
        try:
            return self.cdp.call("Network.getCookies", {"urls": [SITE]}).get("cookies", [])
        except Exception as ex:
            log.warning("Mediaset: cookie di Chrome non leggibili: %s", ex)
            return []

    def login_state(self):
        """{"required", "logged", "user"}: collegati se Chrome ha il cookie di sessione di Gigya
        (glt_<chiave>), che c'è solo dopo l'accesso e sparisce uscendo."""
        logged = any(c.get("name", "").startswith("glt_") for c in self._cookies())
        return {"available": True, "required": True, "logged": logged,
                "user": (self.prefs.get("ms_user") or "") if logged else ""}

    def _tab(self):
        tab = HiddenTab(self.cdp, SITE)
        t0 = time.monotonic()
        while time.monotonic() - t0 < GIGYA_WAIT:
            try:
                if tab.eval(GIGYA_READY, timeout=5):
                    return tab
            except Exception:
                pass                                   # pagina ancora in caricamento
            time.sleep(0.5)
        tab.close()
        raise TimeoutError("libreria di accesso di Mediaset non pronta")

    def login(self, email, password):
        email, password = (email or "").strip(), password or ""
        if not email or not password:
            return {"ok": False, "error": "Scrivi email e password"}
        if not self.cdp:
            return {"ok": False, "error": "Chrome non raggiungibile"}
        try:
            with self._tab() as tab:
                r = tab.eval(gigya_login_js(email, password), timeout=30) or {}
                code = r.get("errorCode")
                if code == 0:
                    time.sleep(1.5)                    # i cookie della sessione arrivano subito dopo
        except Exception as ex:
            log.warning("Mediaset: accesso non riuscito: %s", ex)
            return {"ok": False, "error": "Mediaset non risponde, riprova tra poco"}
        if code != 0:
            log.info("Mediaset: accesso rifiutato (%s %s)", code, r.get("errorMessage"))
            if code in NEEDS_SITE:
                return {"ok": False, "site": True,
                        "error": "Mediaset chiede di completare l'accesso sul sito (es. il controllo «non sono un robot»)"}
            return {"ok": False, "error": login_message(code, r.get("errorMessage"))}
        self.prefs.set("ms_user", r.get("email") or email)
        st = self.login_state()
        log.info("Mediaset: accesso riuscito; cookie: %s", ", ".join(c["name"] for c in self._cookies()))
        if not st["logged"]:
            # Gigya ha detto sì ma il cookie atteso non c'è: lo si segnala invece di fingere
            return {"ok": False, "error": "Accesso riuscito, ma la sessione non risulta salvata in Chrome"}
        return dict(st, ok=True)

    def logout(self):
        """Esce dall'account: con la libreria del sito (chiude anche la sessione condivisa
        di login.mediaset.it), poi via i cookie glt_ rimasti."""
        if self.cdp:
            try:
                with self._tab() as tab:
                    tab.eval("new Promise(r => gigya.accounts.logout({callback: r})).then(() => true)", timeout=20)
            except Exception as ex:
                log.warning("Mediaset: uscita con la libreria non riuscita: %s", ex)
            for c in self._cookies():
                if c["name"].startswith("glt_"):
                    try:
                        self.cdp.call("Network.deleteCookies", {"name": c["name"], "domain": c["domain"],
                                                                "path": c.get("path", "/")})
                    except Exception as ex:
                        log.warning("Mediaset: cookie %s: %s", c["name"], ex)
        self.prefs.set("ms_user", "")
        return self.login_state()

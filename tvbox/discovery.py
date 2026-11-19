"""discovery+: accesso all'account (login) fatto da tvd, come per Mediaset.

Il sito (piattaforma "Bolt" di Warner Bros. Discovery) protegge l'accesso con Arkose, un
controllo anti-robot invisibile il cui gettone lo genera il sito stesso: per questo l'accesso
non chiama l'API ma compila il modulo vero del sito (www.discoveryplus.com/auth/login, campi in
uno shadow DOM) in una scheda nascosta del Chrome della TV (cdp.HiddenTab), con email e password
scritte nella schermata di tvbox. Cookie e sessione li imposta il sito, come accedendo a mano;
la password non si salva. Se Arkose chiede una verifica visibile, l'accesso si fa una volta sul
sito.

Collegati o no: il sito ha sempre un gettone nel cookie "st" (dominio .prd.api.discoveryplus.com),
un JWT con "anonymous": true finché non si accede; dopo l'accesso "anonymous" è false.
"""
import base64
import json
import time

from .cdp import HiddenTab
from .util import log

SITE = "https://www.discoveryplus.com/it/it"
LOGIN_URL = "https://www.discoveryplus.com/auth/login?flow=login"
COOKIE_URLS = ["https://default.any-emea.prd.api.discoveryplus.com/",
               "https://default.any-any.prd.api.discoveryplus.com/",
               "https://www.discoveryplus.com/"]
FORM_WAIT = 40          # secondi per avere il modulo di accesso (la pagina è pesante)
RESULT_WAIT = 30        # secondi per la risposta dopo "Continua"

# tutti gli elementi della pagina, anche dentro gli shadow DOM
_ALL = ("(() => { const all = []; const walk = r => r.querySelectorAll('*').forEach(e => "
        "{ all.push(e); if (e.shadowRoot) walk(e.shadowRoot); }); walk(document); return all; })()")
_FIELDS = ("const a = " + _ALL + ";"
           "const em = a.find(e => e.tagName === 'INPUT' && e.type === 'email');"
           "const pw = a.find(e => e.tagName === 'INPUT' && e.type === 'password');")
FORM_READY = "(() => { " + _FIELDS + " return !!(em && pw); })()"
# messaggio d'errore del modulo (es. "L'indirizzo e-mail non esiste…"), non il banner dei cookie
ERROR_JS = ("(() => { const a = " + _ALL + "; const t = a.filter(e => /alert/i.test(e.getAttribute('role') || '')"
            " || /error/i.test(String(e.className || ''))).map(e => (e.textContent || '').trim())"
            ".filter(x => x && x.length < 300 && !/privacy|cookie/i.test(x)); return t[0] || ''; })()")
# verifica di Arkose a schermo (quella invisibile non conta)
CHALLENGE_JS = ("(() => [...document.querySelectorAll('iframe')].some(f => /arkose|funcaptcha/i.test("
                "(f.src || '') + (f.title || '')) && f.getBoundingClientRect().width > 100"
                " && f.getBoundingClientRect().height > 100))()")


def fill_js(email, password):
    """Espressione JS: scrive email e password nel modulo e preme "Continua"; true se fatto."""
    return ("(() => { " + _FIELDS + " if (!em || !pw) return false;"
            "const set = (el, v) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')"
            ".set.call(el, v); el.dispatchEvent(new Event('input', {bubbles: true, composed: true}));"
            " el.dispatchEvent(new Event('change', {bubbles: true, composed: true})); };"
            f"set(em, {json.dumps(email)}); set(pw, {json.dumps(password)});"
            "const f = pw.closest('form');"
            "const b = (f && f.querySelector('button[type=submit]')) || a.find(e => e.tagName === 'BUTTON'"
            " && /^(continua|accedi|sign in)$/i.test((e.textContent || '').trim()));"
            "if (!b) return false; setTimeout(() => b.click(), 300); return true; })()")


def token_claims(cookies):
    """Contenuto del gettone "st" (JWT) dei cookie di Chrome, None se non c'è o è illeggibile."""
    for c in cookies or []:
        if c.get("name") != "st":
            continue
        parts = (c.get("value") or "").split(".")
        if len(parts) != 3:
            continue
        try:
            return json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        except (ValueError, json.JSONDecodeError):
            continue
    return None


def is_logged(claims, now=None):
    """Collegati: gettone non anonimo e non scaduto."""
    if not isinstance(claims, dict) or claims.get("anonymous") is not False:
        return False
    exp = claims.get("exp")
    return not isinstance(exp, (int, float)) or exp > (now if now is not None else time.time())


class Discovery:
    def __init__(self, prefs, cdp=None):
        self.prefs, self.cdp = prefs, cdp

    def _cookies(self):
        if not self.cdp:
            return []
        try:
            return self.cdp.call("Network.getCookies", {"urls": COOKIE_URLS}).get("cookies", [])
        except Exception as ex:
            log.warning("discovery+: cookie di Chrome non leggibili: %s", ex)
            return []

    # ---------- GET /api/discovery?action=status|login|logout|site ----------
    def login_state(self):
        """{"available", "required", "logged", "user"}: il catalogo gratuito si vede anche senza
        account, quindi l'accesso non è obbligatorio."""
        logged = is_logged(token_claims(self._cookies()))
        return {"available": True, "required": False, "logged": logged,
                "user": (self.prefs.get("dplus_user") or "") if logged else ""}

    def login(self, email, password):
        email, password = (email or "").strip(), password or ""
        if not email or not password:
            return {"ok": False, "error": "Scrivi email e password"}
        if not self.cdp:
            return {"ok": False, "error": "Chrome non raggiungibile"}
        error, challenge, logged = "", False, False
        try:
            with HiddenTab(self.cdp, LOGIN_URL) as tab:
                t0 = time.monotonic()
                while not self._try(tab, FORM_READY):
                    if time.monotonic() - t0 > FORM_WAIT:
                        raise TimeoutError("modulo di accesso non pronto")
                    time.sleep(0.5)
                if not tab.eval(fill_js(email, password), timeout=10):
                    raise RuntimeError("pulsante del modulo non trovato")
                t0 = time.monotonic()
                while time.monotonic() - t0 < RESULT_WAIT:
                    time.sleep(0.8)
                    if is_logged(token_claims(self._cookies())):
                        logged = True
                        break
                    error = self._try(tab, ERROR_JS) or ""
                    if error:
                        break
                    if self._try(tab, CHALLENGE_JS):
                        challenge = True
                        break
        except Exception as ex:
            log.warning("discovery+: accesso non riuscito: %s", ex)
            return {"ok": False, "error": "discovery+ non risponde, riprova tra poco"}
        if logged:
            self.prefs.set("dplus_user", email)
            log.info("discovery+: accesso riuscito")
            return dict(self.login_state(), ok=True)
        if challenge:
            log.info("discovery+: il sito chiede la verifica anti-robot")
            return {"ok": False, "site": True,
                    "error": "discovery+ chiede di completare l'accesso sul sito (verifica «non sono un robot»)"}
        log.info("discovery+: accesso rifiutato (%s)", error or "nessuna risposta")
        return {"ok": False, "error": error or "Accesso non riuscito: nessuna risposta da discovery+"}

    @staticmethod
    def _try(tab, expr):
        try:
            return tab.eval(expr, timeout=5)
        except Exception:
            return None                               # pagina ancora in caricamento

    def logout(self):
        """Esce dall'account togliendo il gettone "st": il sito, alla prossima visita, ne prende
        uno anonimo nuovo (come un browser appena aperto)."""
        for c in self._cookies():
            if c.get("name") == "st":
                try:
                    self.cdp.call("Network.deleteCookies", {"name": "st", "domain": c["domain"],
                                                            "path": c.get("path", "/")})
                except Exception as ex:
                    log.warning("discovery+: cookie st: %s", ex)
        self.prefs.set("dplus_user", "")
        return self.login_state()

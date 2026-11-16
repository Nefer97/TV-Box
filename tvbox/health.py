"""Sorveglianza delle dirette: il video avanza davvero? (decisione pura, provata dai test)

Stato per canale: Watch(canale, aperto_alle). Si chiama step() ogni 2 s con lo stato del video
letto dalla pagina (__tv.health()): restituisce True una sola volta, quando il video è fermo da
STALL secondi dopo la partenza (GRACE), senza che sia una pausa voluta dall'utente.
"""
import time

from .util import log

GRACE = 25          # secondi per far partire il canale
STALL = 20          # secondi senza avanzare = fermo


class Watch:
    def __init__(self, cid, opened_at):
        self.cid, self.opened_at = cid, opened_at
        self.last_t, self.moved_at, self.done = None, opened_at, False

    def step(self, st, now):
        if self.done:
            return False
        t = (st or {}).get("t")
        if now - self.opened_at < GRACE or (st or {}).get("user") or (t is not None and t != self.last_t):
            self.last_t, self.moved_at = t, now
            return False
        if now - max(self.moved_at, self.opened_at + GRACE) < STALL:     # il tempo di partenza non conta
            return False
        self.done = True
        return True


def may_reopen(history, now, limit=3, window=600):
    """Riaperture recenti ancora ammesse? (al massimo `limit` in `window` secondi)"""
    recent = [t for t in history if now - t < window]
    return len(recent) < limit, recent


class HealthMixin:
    """La classe TV la eredita: _health_tick() viene chiamata dalla sorveglianza ogni 2 s."""

    # ---------- dirette che si riparano da sole ----------
    def _health_tick(self, url):
        """Ogni 2 s: il video della visione (diretta o episodio) avanza? Fermo da 20 s senza una
        pausa voluta: si toglie l'allargamento; se il sito chiede di accedere lo si dice,
        altrimenti una diretta viene riaperta (al massimo 3 volte in 10 minuti)."""
        sess = self.session
        if not sess or not sess.watch or sess.watch.done:
            return
        if self.panel or self.asleep or self.on_launcher(url):
            return
        now = time.monotonic()
        st = self.cdp.eval("window.__tv && __tv.health ? __tv.health() : null", timeout=3) or {}
        if not sess.watch.step(st, now):
            return
        log.warning("video fermo: %s (%s)", sess, st)
        self.cdp.eval("window.__tv && __tv.exitFull()", timeout=3)
        time.sleep(1)
        if self.cdp.eval("!!(window.__tv && __tv.loginWall && __tv.loginWall())", timeout=3):
            self.toast("Il sito chiede di accedere · tieni premuto OK per il puntatore")
            return
        ok, self._reopens = may_reopen(self._reopens, now)
        if not sess.reopen or not ok:
            self.toast("Il video si è fermato · MENU per tornare indietro")
            return
        self._reopens.append(now)
        self.toast("La diretta si è fermata: la riavvio")
        time.sleep(1.5)
        self.post(self._reopen, sess)

    def _reopen(self, sess):
        """Riapre la diretta solo se nel frattempo non si è aperto altro (la richiesta aspetta
        in coda dietro alle azioni dell'utente)."""
        if self.session is sess:
            self.open(sess.sid)

"""Sorveglianza delle dirette: il video avanza davvero? (decisione pura, provata dai test)

Stato per canale: Watch(canale, aperto_alle). Si chiama step() ogni 2 s con lo stato del video
letto dalla pagina (__tv.health()): restituisce True una sola volta, quando il video è fermo da
STALL secondi dopo la partenza (GRACE), senza che sia una pausa voluta dall'utente.
"""
import time

from .prefs import PROGRESS_MAX
from .util import log

GRACE = 25          # secondi per far partire il canale
STALL = 20          # secondi senza avanzare = fermo
PROGRESS_EVERY = 15     # ogni quanti secondi si salva dove si è arrivati in un episodio
RESUME_MIN = 60         # si riprende solo dopo il primo minuto…
RESUME_TAIL = 120       # …e non negli ultimi 2 minuti (lì si riparte dall'inizio)


def resume_point(saved):
    """Da dove riprendere un episodio ([secondi, durata, quando] salvati), None = dall'inizio."""
    if not saved:
        return None
    t, d = saved[0], saved[1]
    return t if RESUME_MIN <= t <= d - RESUME_TAIL else None


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
        if not sess or self.panel or self.asleep or self.on_launcher(url):
            return
        episode = sess.what == "episode"                     # degli episodi si ricorda il punto (session.EPISODE)
        if not episode and (not sess.watch or sess.watch.done):
            return
        now = time.monotonic()
        st = self.cdp.eval("window.__tv && __tv.health ? __tv.health() : null", timeout=3) or {}
        if episode:
            self._progress_tick(sess, st, now)
            if st.get("video") and not st.get("paused") and (st.get("t") or 0) > 2 and not sess.seek_shown:
                sess.seek_shown = True                       # all'inizio: barra per qualche secondo
                self.seekbar(hold=self.SEEKBAR_START)
            self._episode_tick(sess, st, now)
        if not sess.watch or sess.watch.done or not sess.watch.step(st, now):
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

    # ---------- episodi: dove si è arrivati ----------
    def _progress_tick(self, sess, st, now):
        """Riapre l'episodio al punto salvato appena il video c'è; poi ogni PROGRESS_EVERY
        secondi salva il punto (e la durata) in prefs, sotto l'indirizzo dell'episodio."""
        t, d = st.get("t"), st.get("d")
        if not st.get("video") or not isinstance(t, (int, float)) or not isinstance(d, (int, float)) or d <= 0:
            return
        if sess.resume_at is not None:
            if (st.get("ready") or 0) < 1:
                return                                       # il video non sa ancora dove andare
            target, sess.resume_at = sess.resume_at, None
            if t < target - 5 and self.cdp.eval(f"!!(window.__tv && __tv.seekTo({float(target)}))", timeout=3):
                m, s = divmod(int(target), 60)
                self.toast(f"Riprendo da {m // 60}:{m % 60:02d}:{s:02d}" if m >= 60 else f"Riprendo da {m}:{s:02d}")
                sess.progress_saved = now                    # il punto vecchio non va sovrascritto con 0
            return
        if t < 5 or now - sess.progress_saved < PROGRESS_EVERY:
            return
        sess.progress_saved = now
        url, entry = sess.key, [round(float(t), 1), round(float(d), 1), int(time.time())]
        self.prefs.update("progress", lambda p: dict(
            sorted({**(p or {}), url: entry}.items(), key=lambda kv: kv[1][2])[-PROGRESS_MAX:]))

    def _reopen(self, sess):
        """Riapre la diretta solo se nel frattempo non si è aperto altro (la richiesta aspetta
        in coda dietro alle azioni dell'utente)."""
        if self.session is sess:
            self.open(sess.sid)

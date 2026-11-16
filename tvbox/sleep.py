"""Timer di spegnimento e schermo spento (anche dopo tanto salvaschermo).

La classe TV li eredita da SleepMixin.
"""
import time

from .util import log


SLEEP_STEPS = [0, 30, 60, 90, 120]                  # timer di spegnimento (minuti, 0 = spento)


class SleepMixin:
    # ---------- timer di spegnimento ----------
    def sleep_left(self):
        """Minuti che mancano (arrotondati per eccesso), 0 = timer spento."""
        if not self.sleep_at:
            return 0
        return max(1, int((self.sleep_at - time.monotonic() + 59) // 60))

    def sleep_set(self, minutes):
        self.sleep_at = time.monotonic() + minutes * 60 if minutes else 0.0
        self.sleep_warned = False
        log.info("timer di spegnimento: %s", f"{minutes} min" if minutes else "spento")
        return {"minutes": self.sleep_left()}

    def _sleep_tick(self):
        if not self.sleep_at or self.asleep:
            return
        left = self.sleep_at - time.monotonic()
        if left <= 0:
            self.post(self.sleep_now)
        elif left <= 60 and not self.sleep_warned:
            self.sleep_warned = True
            self.toast("Spegnimento tra 1 minuto · premi un tasto per annullare")

    def sleep_now(self, why="timer"):
        """Fine del timer (o salvaschermo acceso troppo a lungo): si torna alla home e lo schermo
        si spegne (segnale video fermo); il primo tasto del telecomando lo riaccende. La home
        sa di essere "addormentata" (#sleep): niente salvaschermo a schermo spento."""
        self.sleep_at, self.sleep_warned = 0.0, False
        log.info("schermo spento (%s)", why)
        self.home(page="sleep")
        time.sleep(1)
        self.display.blank(True)
        self.asleep = True

    def wake(self):
        self.asleep = False
        self.display.blank(False)
        try:
            self.cdp.eval("window.__tvWake && __tvWake()", timeout=3)
        except Exception:
            pass
        log.info("schermo riacceso")

    def _saver_tick(self, url):
        """Salvaschermo acceso da troppo tempo (Impostazioni, di serie 1 ora): schermo spento."""
        off = self.prefs.get("saver_off")
        if not off or self.asleep or not self.on_launcher(url):
            return
        since = self.cdp.eval("window.__tvSaverSince || 0", timeout=3) or 0
        if since and time.time() * 1000 - since > off * 60000:
            self.post(self.sleep_now, "salvaschermo")

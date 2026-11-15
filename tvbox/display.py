"""Risoluzione dello schermo (xrandr).

Tre cose, tutte qui:
  * la risoluzione "normale" scelta in Impostazioni (o quella preferita dallo schermo);
  * la prova di una risoluzione nuova: se entro 15 s non viene confermata, si torna indietro;
  * la risoluzione più bassa durante i video ("video_mode"): il Mac mini disegna tutto senza
    scheda grafica, quindi meno punti = video più fluido.
"""
import re
import subprocess
import threading
import time

from .util import log

TRIAL_SECONDS = 15


def parse_xrandr(out):
    """(uscita, (larghezza, altezza) attuali, modo preferito "LxA", modi disponibili)."""
    cur = re.search(r"current (\d+) x (\d+)", out)
    output, pref, modes, inside = None, None, [], False
    for line in out.splitlines():
        if not line.startswith(" "):
            inside = " connected" in line
            if inside and output is None:
                output = line.split()[0]
            continue
        if inside and output:
            m = re.match(r"\s+(\d+x\d+)\S*\s+(.*)", line)
            if m:
                if m.group(1) not in modes:
                    modes.append(m.group(1))
                if "+" in m.group(2) and pref is None:
                    pref = m.group(1)
    if pref is None and modes:
        pref = modes[0]
    return output, (int(cur.group(1)), int(cur.group(2))) if cur else None, pref, modes


def scale_for(height):
    """Ingrandimento di Chrome: il launcher è pensato per 720 righe. Sotto le 900 righe
    resta 1.0 (un valore non intero come 1.07 rende tutto sfocato); 1080 -> 1.5."""
    return 1.0 if height < 900 else round(height / 720, 2)


class Display:
    def __init__(self, prefs, video_mode=""):
        self.prefs = prefs
        self.video_mode = (video_mode or "").strip()
        self.lowres = False
        self.trial = None                 # (modo provato, modo di prima, timer)
        self.lock = threading.RLock()
        self.on_change = None             # chiamata dopo ogni cambio (la TV adatta la finestra)
        self.on_trial_expired = None      # chiamata se la prova scade senza conferma

    # ---------- xrandr ----------
    def query(self):
        out = subprocess.run(["xrandr", "--query"], capture_output=True, text=True, timeout=5).stdout
        return parse_xrandr(out)

    def apply(self, mode):
        """Imposta una risoluzione ("auto" = quella preferita dallo schermo)."""
        output, _, _, modes = self.query()
        if not output:
            return False
        if mode != "auto" and mode not in modes:
            log.warning("risoluzione %s non disponibile su %s", mode, output)
            return False
        args = ["--auto"] if mode == "auto" else ["--mode", mode]
        r = subprocess.run(["xrandr", "--output", output] + args, capture_output=True, text=True, timeout=10)
        log.info("schermo -> %s (%s)", mode, r.returncode)
        if r.returncode == 0 and self.on_change:
            time.sleep(1.5)
            self.on_change()
        return r.returncode == 0

    # ---------- risoluzione normale ----------
    def saved(self):
        return self.prefs.get("screen")["mode"]

    def video_low(self):
        return bool(self.video_mode) and self.prefs.get("screen")["video_low"]

    def full_mode(self):
        """Quella scelta, se lo schermo collegato la offre; altrimenti "auto"
        (cambiando TV non si resta mai su una risoluzione impossibile)."""
        m = self.saved()
        if m != "auto":
            try:
                if m in self.query()[3]:
                    return m
            except Exception:
                pass
        return "auto"

    def scale_factor(self):
        try:
            _, cur, pref, _ = self.query()
            m = self.full_mode()
            m = pref if m == "auto" else m
            h = int(m.split("x")[1]) if m else (cur or (1280, 720))[1]
            return scale_for(h)
        except Exception as ex:
            log.warning("xrandr non disponibile: %s", ex)
            return 1.0

    def startup(self):
        if self.video_mode or self.saved() != "auto":
            try:
                self.apply(self.full_mode())
            except Exception as ex:
                log.warning("xrandr: %s", ex)

    def info(self):
        out, cur, pref, modes = self.query()
        return {"output": out, "current": f"{cur[0]}x{cur[1]}" if cur else None,
                "preferred": pref, "saved": self.saved(), "modes": modes,
                "video_mode": self.video_mode, "video_low": self.prefs.get("screen")["video_low"],
                "trial": bool(self.trial)}

    # ---------- schermo spento (timer di spegnimento) ----------
    @staticmethod
    def blank(off):
        """Spegne/riaccende il segnale video (DPMS): la TV va in "nessun segnale" e di solito
        in standby da sola. La sessione X ha il DPMS disattivato: lo si accende solo qui."""
        cmds = ([["xset", "+dpms"], ["xset", "dpms", "force", "off"]] if off
                else [["xset", "dpms", "force", "on"], ["xset", "-dpms"], ["xset", "s", "reset"]])
        for c in cmds:
            subprocess.run(c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)

    # ---------- durante i video ----------
    def set_lowres(self, on):
        with self.lock:
            if not self.video_mode or on == self.lowres or self.trial:
                return
            if self.apply(self.video_mode if on else self.full_mode()):
                self.lowres = on

    def set_video_low(self, on):
        self.prefs.update("screen", lambda s: dict(s, video_low=bool(on)))
        log.info("risoluzione bassa nei video: %s", on)
        if not on:
            self.set_lowres(False)

    # ---------- prova di una risoluzione ----------
    def try_mode(self, mode):
        with self.lock:
            if self.trial:
                self.trial[2].cancel()
                prev = self.trial[1]
            else:
                prev = self.saved()
            self.trial = None
            if not self.apply(mode):
                return False
            self.lowres = False
            timer = threading.Timer(TRIAL_SECONDS, self._expired)
            timer.daemon = True
            self.trial = (mode, prev, timer)
            timer.start()
            return True

    def _expired(self):
        if self.on_trial_expired:
            self.on_trial_expired()
        else:
            self.revert()

    def keep(self):
        with self.lock:
            if not self.trial:
                return None
            mode, _, timer = self.trial
            timer.cancel()
            self.trial = None
            self.prefs.update("screen", lambda s: dict(s, mode=mode))
            log.info("risoluzione scelta: %s", mode)
            return mode

    def revert(self):
        with self.lock:
            if not self.trial:
                return
            _, prev, timer = self.trial
            timer.cancel()
            self.trial = None
            m = prev if prev == "auto" or prev in self.query()[3] else "auto"
            log.info("prova non confermata: torno a %s", m)
            self.apply(m)

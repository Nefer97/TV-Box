"""Apple Remote: dal dispositivo (evdev) ai tasti logici.

RemoteLogic non sa niente di evdev né di orologi veri: riceve (tasto, valore, istante) e
restituisce eventi. Così si prova con i test, senza telecomando.

Tasti fisici (nomi):  up down left right  ok  menu  play  enter  home
    telecomando bianco:     + − |◀◀ ▶▶|, centrale = "play" (fa da OK), MENU
    telecomando alluminio:  ha un centrale vero ("enter") e ▶❚❚ separato

Eventi prodotti:
    ("arrow", dir, n)      freccia; n = 0 alla pressione, 1, 2… nelle ripetizioni
    ("pointer", dir, px)   freccia tenuta in modalità puntatore: sposta di px
    ("ok",) ("ok_long",)   ("menu",) ("menu_long",)   ("play",)   ("home",)
"""
import threading
import time

from .util import log

ARROWS = ("up", "down", "left", "right")


class RemoteLogic:
    def __init__(self, opt, pointer=lambda: False):
        self.long_s = opt("remote.long_press_ms", 800) / 1000
        self.ok_long_s = opt("remote.ok_long_press_ms", 1500) / 1000
        self.repeat_s = opt("remote.repeat_ms", 170) / 1000
        # il telecomando Apple allunga anche le pressioni brevi: la ripetizione parte solo
        # se la freccia resta premuta almeno questo tempo (altrimenti 1 pressione = 2-3 passi)
        self.repeat_delay_s = opt("remote.repeat_delay_ms", 600) / 1000
        # il ricevitore a infrarossi a volte "spezza" una pressione in due: una nuova pressione
        # della stessa freccia così vicina al rilascio è la stessa pressione
        self.debounce_s = opt("remote.debounce_ms", 220) / 1000
        self.pointer_speed = float(opt("remote.pointer_speed_px_s", 640))
        self.pointer_delay_s = opt("remote.pointer_delay_ms", 300) / 1000
        self.pointer = pointer
        self.aluminium = False
        self.press_t = 0.0
        self.last_rep = 0.0
        self.rep = 0
        self.nrep = 0
        self.last_up = {}
        self.ghost = None
        self.held = {}                     # pulsante -> [istante di pressione, lunga già scattata]

    # ---------- pulsanti ----------
    def _button(self, key):
        if key == "enter":
            self.aluminium = True
            return "ok"
        if key == "play":
            return "play" if self.aluminium else "ok"
        return key if key in ("menu", "home") else None

    def handle(self, key, val, now):
        if key in ARROWS:
            return self._arrow(key, val, now)
        name = self._button(key)
        if not name:
            return []
        if name == "home":
            return [("home",)] if val == 1 else []
        if val == 1:
            self.held[name] = [now, False]
        elif val == 0:
            h = self.held.pop(name, None)
            if h and not h[1]:
                return [(name,)]
        return []

    def tick(self, now):
        """Da chiamare spesso: fa scattare la pressione lunga mentre il tasto è ancora giù."""
        out = []
        for name, h in self.held.items():
            if not h[1] and now - h[0] >= (self.ok_long_s if name == "ok" else self.long_s):
                h[1] = True
                out.append((name + "_long",))
        return out

    # ---------- frecce ----------
    def _arrow(self, d, val, now):
        if val == 0:
            self.last_up[d] = now
            log.info("freccia %s rilasciata dopo %d ms (%d ripetizioni)%s", d,
                     (now - self.press_t) * 1000, self.nrep, " [doppione]" if self.ghost == d else "")
            self.ghost = None
            return []
        if val == 1 and now - self.last_up.get(d, -9) < self.debounce_s:
            self.ghost, self.nrep = d, 0          # doppione: ignorato fino al rilascio
            return []
        if self.ghost == d:
            self.nrep += 1
            return []
        if val == 1:
            self.rep, self.last_rep, self.press_t, self.nrep = 0, now, now, 0
            return [("arrow", d, 0)]
        self.nrep += 1
        if self.pointer():
            if now - self.press_t < self.pointer_delay_s:
                return []
            # primo passo dopo l'attesa: intervallo tipico di ripetizione (~33 ms)
            dt = 0.033 if self.last_rep <= self.press_t else min(now - self.last_rep, 0.1)
            self.last_rep = now
            return [("pointer", d, max(1, round(self.pointer_speed * dt)))]
        if now - self.press_t < self.repeat_delay_s or now - self.last_rep < self.repeat_s:
            return []
        self.rep += 1
        self.last_rep = now
        return [("arrow", d, self.rep)]


class RemoteReader(threading.Thread):
    """Legge il telecomando con evdev (in esclusiva) e consegna gli eventi a on_event."""

    def __init__(self, logic, on_event, match=("IR Receiver",)):
        super().__init__(daemon=True)
        self.logic = logic
        self.on_event = on_event
        self.match = [m.lower() for m in match]
        self.lock = threading.Lock()

    def _codes(self):
        from evdev import ecodes as E
        return {E.KEY_VOLUMEUP: "up", E.KEY_VOLUMEDOWN: "down", E.KEY_UP: "up", E.KEY_DOWN: "down",
                E.KEY_BACK: "left", E.KEY_FORWARD: "right", E.KEY_LEFT: "left", E.KEY_RIGHT: "right",
                E.KEY_ENTER: "enter", E.KEY_PLAYPAUSE: "play", E.KEY_MENU: "menu", E.KEY_ESC: "menu",
                E.KEY_HOME: "home", E.KEY_HOMEPAGE: "home"}

    def _emit(self, events):
        for e in events:
            try:
                self.on_event(e)
            except Exception as ex:
                log.warning("evento %s: %s", e, ex)

    def _ticker(self):
        while True:
            time.sleep(0.05)
            with self.lock:
                ev = self.logic.tick(time.monotonic())
            self._emit(ev)

    def find(self):
        import evdev
        for path in evdev.list_devices():
            try:
                d = evdev.InputDevice(path)
            except OSError:
                continue
            if not d.name.startswith("tvbox-") and any(m in d.name.lower() for m in self.match):
                return d
            d.close()
        return None

    def run(self):
        from evdev import ecodes as E
        codes = self._codes()
        threading.Thread(target=self._ticker, daemon=True).start()
        while True:
            dev = self.find()
            if not dev:
                log.info("telecomando non trovato, riprovo...")
                time.sleep(5)
                continue
            log.info("telecomando: %s (%s)", dev.name, dev.path)
            try:
                dev.grab()
            except OSError as ex:
                log.warning("grab fallito: %s", ex)
            try:
                for ev in dev.read_loop():
                    if ev.type == E.EV_KEY and ev.code in codes:
                        with self.lock:
                            out = self.logic.handle(codes[ev.code], ev.value, time.monotonic())
                        self._emit(out)
            except OSError as ex:
                log.warning("telecomando perso: %s", ex)
            finally:
                try:
                    dev.close()
                except Exception:
                    pass
            time.sleep(1)

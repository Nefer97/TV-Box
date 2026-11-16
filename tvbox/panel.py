"""Pannello cambio canale sopra le dirette, sipario durante i cambi e banner del programma.

La classe TV li eredita da PanelMixin. Il pannello e il sipario vengono "prenotati" nella
pagina che sta per nascere (vedi _book), così restano a schermo durante il cambio canale.
"""
import json
import threading
import time

from .browser import overlay_script, panel_script
from .sleep import SLEEP_STEPS
from .util import log


# script "prenotato" nella pagina del canale nuovo: appena esiste l'elemento radice (nel primo
# istante della pagina non c'è ancora: lo si aspetta con un MutationObserver) lo colora di blu
# e ci aggancia pannello e sipario, senza aspettare il corpo della pagina (che su Mediaset
# arriva tardi, dopo script pesanti). Va eseguito solo nella pagina principale.
BOOT_START = """(function () {
  var start = function () {
    var e = document.documentElement;
    if (!e) return false;
    e.style.setProperty('background', '#0b1020', 'important');
    try { window.__tvp.open(d); } catch (x) { console.error('[pannello]', x); }
    return true;
  };
  if (!start()) { var mo = new MutationObserver(function () { if (start()) mo.disconnect(); });
                  mo.observe(document, { childList: true }); }
})();"""
DARK = {"r": 11, "g": 16, "b": 32, "a": 1}      # fondo di Chrome durante il cambio canale


class PanelMixin:
    # ---------- pannello cambio canale ----------
    def panel_active(self):
        if not self.panel:
            return False
        try:
            self.panel = bool(self.cdp.eval("!!(window.__tvp && __tvp.isOpen())", timeout=3))
        except Exception:
            self.panel = False
        return self.panel

    def panel_data(self):
        od = {}
        try:
            od = self.epg.onair()
        except Exception as ex:
            log.warning("palinsesti: %s", ex)
        chans = []
        for sid in self.channel_list():
            s = self.services[sid]
            o = od.get(s.get("onair") or "") or {}
            chans.append({"id": sid, "label": s["label"], "color": s.get("color"),
                          "title": o.get("title", ""), "start": o.get("start", 0), "end": o.get("end", 0),
                          "image": o.get("image", ""), "desc": (o.get("desc") or "")[:300]})
        return {"channels": chans, "current": self.current, "vol": self.volume(0),
                "videoLow": self.display.video_low() if self.display.video_mode else None,
                "sleep": self.sleep_left()}

    def panel_step(self, key):
        """◄ ► su una diretta: il pannello si apre già sul canale precedente / successivo."""
        self.panel_open(step=-1 if key == "left" else 1)

    def panel_open(self, key=None, step=0):
        js = panel_script()
        d = self.panel_data()
        d["step"] = step
        data = json.dumps(d)
        self.panel = bool(self.cdp.eval(f"{js}\n;window.__tvp.open({data})", timeout=6))
        log.info("pannello: %s", "aperto" if self.panel else "non riuscito")

    def panel_close(self, key=None):
        self.panel = False
        try:
            self.cdp.js("__tvp.close", timeout=3)
        except Exception:
            pass

    def panel_move(self, key):
        self.cdp.js("__tvp.move", key, timeout=3)

    def panel_volume(self, key):
        v = self.volume(self._step(key))
        if v is not None:
            self.osd_volume(v)                      # stessa barra del volume di quando si guarda

    def panel_ok(self, key=None):
        r = self.cdp.eval("window.__tvp ? __tvp.ok() : null", timeout=3)
        if not isinstance(r, dict):
            return
        a = r.get("act")
        if a == "open":
            sid = r.get("id")
            if sid == self.current:
                return self.panel_close()
            self.panel_switch(sid)
        elif a == "video":
            on = bool(r.get("on"))
            self.display.set_video_low(on)
            self.cdp.js("__tvp.set", "videoLow", on, timeout=3)
        elif a == "sleep":                              # timer: spento -> 30 -> 60 -> 90 -> 120 -> spento
            left = self.sleep_left()
            nxt = next((m for m in SLEEP_STEPS if m > left), 0) if left else SLEEP_STEPS[1]
            self.sleep_set(nxt)
            self.cdp.js("__tvp.set", "sleep", self.sleep_left(), timeout=3)
        elif a == "guide":
            self.home(page="guide")
        elif a == "settings":
            self.home(page="settings")
        elif a == "home":
            self.home()

    def _book(self, data):
        """Prenota pannello e/o sipario nella pagina che sta per nascere (script registrato per i
        documenti nuovi, solo nella pagina principale): la pagina nasce già blu e li disegna
        subito, prima del sito. Il fondo di Chrome diventa blu: niente lampo bianco."""
        boot = ("if (window.top === window) {\n" + panel_script() +
                f"\n;var d = {json.dumps(data)};\n" + BOOT_START + "\n}")
        pending = None
        try:
            pending = self.cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": boot}).get("identifier")
        except Exception as ex:
            log.warning("prenotazione: %s", ex)
        try:
            self.cdp.call("Emulation.setDefaultBackgroundColorOverride", {"color": DARK})
            self.dark_default = True
        except Exception:
            pass
        return pending

    def panel_switch(self, sid):
        """Cambio canale dal pannello senza che il pannello sparisca: resta a schermo, con il
        sipario dietro, mentre il canale nuovo si carica."""
        self.cdp.js("__tvp.set", "busy", sid, timeout=3)
        data = self.panel_data()
        data["current"] = sid
        data["curtain"] = True              # fondo scuro finché il video nuovo non parte
        pending = self._book(data)
        self._switching = True
        try:
            self.open(sid, keep_dark=True)
        finally:
            self._switching = False
        self.panel = True
        threading.Thread(target=self._panel_unbook, args=(sid, pending), daemon=True).start()

    def _panel_unbook(self, sid, pending):
        """Appena il pannello c'è nella pagina nuova (o dopo 15 s) si toglie la prenotazione,
        così un ricaricamento successivo della pagina non lo fa ricomparire."""
        deadline = time.monotonic() + 15
        time.sleep(1)
        while time.monotonic() < deadline and self.current == sid:
            try:
                if self.cdp.eval("!!(window.__tvp && __tvp.isOpen())", timeout=3):
                    break
            except Exception:
                pass
            time.sleep(0.4)
        if pending:
            try:
                self.cdp.call("Page.removeScriptToEvaluateOnNewDocument", {"identifier": pending})
            except Exception:
                pass

    # ---------- banner del programma all'apertura di un canale ----------
    def _banner(self, sid):
        """Quando il video del canale è partito: canale, programma, orario e il successivo."""
        deadline = time.monotonic() + 25
        time.sleep(2)
        while time.monotonic() < deadline and self.current == sid:
            if self.is_player():
                break
            time.sleep(0.7)
        if self.current != sid or self.panel_active():
            return
        time.sleep(1.2)                                 # dopo lo schermo intero
        now = self.epg.for_service(sid)
        nxt = next((p for p in self.epg.guide(sid, hours=6) if p["start"] >= (now.get("end") or 1)), None)
        s = self.services[sid]
        data = {"label": s["label"], "color": s.get("color"), "now": now, "next": nxt}
        js = overlay_script("osd.js")
        if js and self.current == sid:
            try:
                self.cdp.eval(f"{js}\n;window.__tvosd.show({json.dumps(data)})", timeout=5)
            except Exception as ex:
                log.debug("banner: %s", ex)

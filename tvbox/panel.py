"""Pannello cambio canale sopra le dirette (MENU, ◄ ►), disegnato dallo strato TV.

La classe TV lo eredita da PanelMixin. Durante il cambio canale il pannello resta a schermo:
viene prenotato nella pagina del canale nuovo insieme al sipario (LayerMixin.book).
"""
from .session import Session
from .sleep import SLEEP_STEPS
from .util import log


class PanelMixin:
    def panel_active(self):
        if not self.panel:
            return False
        self.panel = bool(self.layer("has", "panel", timeout=3))
        return self.panel

    def panel_data(self, step=0):
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
        return {"channels": chans, "current": self.current, "step": step,
                "videoLow": self.display.video_low() if self.display.video_mode else None,
                "sleep": self.sleep_left()}

    def panel_step(self, key):
        """◄ ► su una diretta: il pannello si apre già sul canale precedente / successivo."""
        self.panel_open(step=-1 if key == "left" else 1)

    def panel_open(self, key=None, step=0):
        self.panel = bool(self.layer("panel", self.panel_data(step), timeout=6))
        log.info("pannello: %s", "aperto" if self.panel else "non riuscito")

    def panel_close(self, key=None):
        self.panel = False
        self.layer("closePanel", timeout=3)

    def panel_move(self, key):
        self.layer("move", key, timeout=3)

    def panel_volume(self, key):
        v = self.volume(self._step(key))
        if v is not None:
            self.osd_volume(v)                      # stessa barra del volume di quando si guarda

    def panel_ok(self, key=None):
        r = self.layer("ok", timeout=3)
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
            self.layer("set", "videoLow", on, timeout=3)
        elif a == "sleep":                              # timer: spento -> 30 -> 60 -> 90 -> 120 -> spento
            left = self.sleep_left()
            nxt = next((m for m in SLEEP_STEPS if m > left), 0) if left else SLEEP_STEPS[1]
            self.sleep_set(nxt)
            self.layer("set", "sleep", self.sleep_left(), timeout=3)
        elif a == "guide":
            self.home(page="guide")
        elif a == "settings":
            self.home(page="settings")
        elif a == "home":
            self.home()

    def panel_switch(self, sid):
        """Cambio canale dal pannello senza che il pannello sparisca: resta a schermo, con il
        sipario dietro, mentre il canale nuovo si carica."""
        s = self.services.get(sid)
        if not s:
            return
        self.layer("set", "busy", sid, timeout=3)
        data = self.panel_data()
        data["current"] = sid
        self.start(Session.for_service(s), panel=data)
        self.panel = True

"""Azioni dei tasti del telecomando: tasti veri, puntatore, video, navigazione assistita.

Sono i metodi che la tabella keys.KEYMAP nomina; la classe TV li eredita da Actions.
"""


class Actions:
    # ---------- azioni: tasti veri ----------
    def key_arrow(self, key):
        self.input.key(key)

    def key_enter(self, key=None):
        self.input.key("enter")

    def key_esc(self, key=None):
        self.input.key("esc")

    def _tv_key(self, code):
        """Tasto con codice da televisore, inviato tramite Chrome (461 indietro, 463 play)."""
        for t in ("rawKeyDown", "keyUp"):
            self.cdp.call("Input.dispatchKeyEvent", {"type": t, "windowsVirtualKeyCode": code,
                                                     "nativeVirtualKeyCode": code})

    def tv_back(self, key=None):
        self._tv_key(461)

    def tv_play(self, key=None):
        self._tv_key(463)

    # ---------- azioni: puntatore ----------
    def pointer_toggle(self, key=None):
        self.pointer = not self.pointer
        self.toast("Puntatore attivo: frecce per muovere, OK per cliccare"
                   if self.pointer else "Puntatore disattivato")
        if self.pointer:
            self.input.move(1, 1)                   # piccolo movimento per mostrarlo

    def pointer_off(self, key=None):
        self.pointer = False
        self.toast("Puntatore disattivato")

    def pointer_nudge(self, key):
        px = int(self.cfg.opt("remote.pointer_nudge_px", 12))
        self.pointer_move(key, px)

    def pointer_move(self, d, px):
        self.input.move({"left": -px, "right": px}.get(d, 0), {"up": -px, "down": px}.get(d, 0))

    def click(self, key=None):
        self.input.click()

    def click_at(self, x, y):
        """Clic "vero" nel punto x,y della pagina, tramite Chrome."""
        base = {"x": x, "y": y, "button": "left", "clickCount": 1}
        self.cdp.call("Input.dispatchMouseEvent", dict(base, type="mouseMoved", button="none"))
        self.cdp.call("Input.dispatchMouseEvent", dict(base, type="mousePressed"))
        self.cdp.call("Input.dispatchMouseEvent", dict(base, type="mouseReleased"))

    # ---------- azioni: video ----------
    def player_toggle(self, key=None):
        r = self.cdp.eval("window.__tv ? __tv.toggle() : false", timeout=3, gesture=True)
        if r == "play":
            self.toast("▶  Riproduci")
        elif r == "pause":
            self.toast("❚❚  Pausa")
        else:
            self.input.key("space")

    def player_volume(self, key):
        v = self.volume(self._step(key))
        if v is not None:
            self.osd_volume(v)

    def player_seek(self, key):
        sec = -int(self.cfg.opt("player.seek_back_s", 10)) if key == "left" \
            else int(self.cfg.opt("player.seek_forward_s", 30))
        if self.cdp.js("__tv.seek", sec, timeout=3):
            self.toast(("▶▶  +" if sec > 0 else "◀◀  −") + f"{abs(sec)} s")

    # ---------- azioni: navigazione assistita ----------
    def nav_move(self, key):
        if not self.cdp.js("__nav.move", key, timeout=4):
            self.input.key(key)

    def nav_ok(self, key=None):
        r = self.cdp.eval("window.__nav ? __nav.activate() : null", timeout=4, gesture=True)
        if isinstance(r, dict) and "x" in r:
            self.click_at(r["x"], r["y"])
        elif not r:
            self.input.key("enter")

    def page_back(self, key=None):
        if self.cdp.eval("!!(window.__nav && __nav.back())", timeout=3):
            return                                   # chiusa la tastiera a schermo
        ret = self.session.return_to if self.session else None
        if ret:                                      # es. episodio Mediaset -> pagina della serie
            return self.home(page=ret)
        if self.cdp.eval("!!(window.__tv && __tv.exitFull())", timeout=3):
            return
        if self.cdp.eval("history.length > 1", timeout=3):
            self.cdp.eval("history.back()", timeout=3)
        else:
            self.home()

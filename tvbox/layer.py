"""Lo strato TV visto da tvd: sipario, banner, volume e avvisi sopra le pagine (inject/layer.js).

La classe TV lo eredita da LayerMixin. Tutto passa da layer(): chiama una funzione dello
strato nella pagina e, se la pagina non ce l'ha ancora (pagina nuova di un sito), prima ce lo
mette. Per la pagina che sta per nascere (cambio canale) lo strato viene "prenotato": nasce
con la pagina, già con il sipario, prima del sito (vedi book()).
"""
import json
import threading
import time

from .browser import layer_script
from .util import log

DARK = {"r": 11, "g": 16, "b": 32, "a": 1}      # fondo di Chrome durante il cambio canale
MISSING = "__tvl?"


class LayerMixin:
    def layer(self, method, *args, timeout=4):
        """Chiama __tvl.<method>(args) nella pagina (argomenti in JSON); None se non riesce."""
        call = f"window.__tvl.{method}({', '.join(json.dumps(a) for a in args)})"
        try:
            r = self.cdp.eval(f"window.__tvl ? {call} : {json.dumps(MISSING)}", timeout=timeout)
            if r == MISSING:
                js = layer_script()
                r = self.cdp.eval(f"{js}\n;{call}", timeout=timeout + 3) if js else None
            return r
        except Exception as ex:
            log.debug("strato TV %s: %s", method, ex)
            return None

    def toast(self, msg):
        self.layer("toast", msg, timeout=2)

    def osd_volume(self, v):
        """Barra del volume in alto a destra, aggiornata a ogni pressione."""
        self.layer("volume", int(v))

    # ---------- la pagina che sta per nascere ----------
    def book(self, curtain=None, panel=None):
        """Prenota lo strato nella pagina nuova (script registrato per i documenti nuovi): la
        pagina nasce blu, con il sipario ("Apro <curtain>…") e/o il pannello, prima del sito.
        Anche il fondo di Chrome diventa blu: niente lampo bianco. Restituisce la prenotazione."""
        boot = layer_script() + f"\n;window.__tvl && __tvl.boot({json.dumps({'curtain': curtain, 'panel': panel})});"
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
        if pending:
            threading.Thread(target=self._unbook, args=(self.session, pending), daemon=True).start()
        return pending

    def _unbook(self, sess, pending):
        """Appena lo strato c'è nella pagina nuova (o dopo 15 s) si toglie la prenotazione, così
        un ricaricamento successivo della pagina non rimette il sipario."""
        deadline = time.monotonic() + 15
        time.sleep(1)
        while time.monotonic() < deadline and self.session is sess:
            if self.layer("has", "curtain", timeout=3) or self.layer("has", "panel", timeout=3):
                break
            time.sleep(0.4)
        try:
            self.cdp.call("Page.removeScriptToEvaluateOnNewDocument", {"identifier": pending})
        except Exception:
            pass

    def clear_dark(self):
        if self.dark_default:
            try:
                self.cdp.call("Emulation.setDefaultBackgroundColorOverride", {})
            except Exception:
                pass
            self.dark_default = False

    # ---------- banner del programma all'apertura di un canale ----------
    def _banner(self, sess):
        """Quando il video del canale è partito: canale, programma, orario e il successivo."""
        deadline = time.monotonic() + 25
        time.sleep(2)
        while time.monotonic() < deadline and self.session is sess:
            if self.is_player():
                break
            time.sleep(0.7)
        if self.session is not sess or self.panel_active():
            return
        time.sleep(1.2)                                 # dopo lo schermo intero
        now = self.epg.for_service(sess.sid)
        nxt = next((p for p in self.epg.guide(sess.sid, hours=6) if p["start"] >= (now.get("end") or 1)), None)
        if self.session is sess:
            self.layer("banner", {"label": sess.title, "now": now, "next": nxt}, timeout=5)

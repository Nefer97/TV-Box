"""Chrome DevTools Protocol: client minimale con un thread lettore.

Alla connessione registra gli script da iniettare in ogni pagina nuova e li esegue anche
sulla pagina già aperta. Ogni script è registrato a parte: se uno fallisce o è lento,
gli altri restano attivi (in V1 uno script pesante in testa bloccava il riquadro giallo).
"""
import json
import threading
import urllib.request

import websocket

from .util import log


class CDP:
    def __init__(self, port, scripts=()):
        self.port = port
        self.scripts = list(scripts)
        self.ws = None
        self.target_id = None
        self.send_lock = threading.Lock()
        self.conn_lock = threading.Lock()
        self.pending = {}
        self.next_id = 1
        self.crashed = threading.Event()

    def _http(self, path, timeout=3):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=timeout) as r:
            return r.read()

    def targets(self):
        return [t for t in json.loads(self._http("/json/list"))
                if t.get("type") == "page" and not t.get("url", "").startswith("devtools://")]

    def close_other_pages(self):
        """Chiude le schede in più (popup aperti dai siti)."""
        try:
            for t in self.targets():
                if t["id"] != self.target_id:
                    self._http(f"/json/close/{t['id']}")
        except Exception as ex:
            log.debug("close_other_pages: %s", ex)

    def ensure(self):
        if self.ws is not None:
            return
        with self.conn_lock:
            if self.ws is not None:
                return
            pages = self.targets()
            if not pages:
                raise ConnectionError("nessuna pagina CDP")
            t = next((p for p in pages if p["id"] == self.target_id), pages[0])
            ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=5, suppress_origin=True)
            ws.settimeout(None)
            self.ws, self.target_id = ws, t["id"]
            threading.Thread(target=self._reader, args=(ws,), daemon=True).start()
            log.info("CDP collegato a %s", t.get("url"))
        self.call("Inspector.enable")
        self.call("Page.enable")        # serve perché gli script restino attivi sulle pagine nuove
        for s in self.scripts:          # prima la registrazione per le pagine future...
            try:
                self.call("Page.addScriptToEvaluateOnNewDocument", {"source": s}, timeout=20)
            except Exception as ex:
                log.warning("registrazione script fallita: %s", ex)
        for s in self.scripts:          # ...poi l'esecuzione sulla pagina attuale
            try:
                self.call("Runtime.evaluate", {"expression": s}, timeout=20)
            except Exception as ex:
                log.warning("script sulla pagina attuale: %s", ex)

    def _reader(self, ws):
        while True:
            try:
                msg = ws.recv()
            except Exception:
                break
            if not msg:
                break
            try:
                data = json.loads(msg)
            except ValueError:
                continue
            mid = data.get("id")
            if mid is not None:
                slot = self.pending.get(mid)
                if slot:
                    slot[1] = data
                    slot[0].set()
            elif data.get("method") == "Inspector.targetCrashed":
                log.warning("renderer in crash")
                self.crashed.set()
            elif data.get("method") == "Inspector.detached":
                break
        if self.ws is ws:
            self.drop()

    def drop(self):
        ws, self.ws = self.ws, None
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        for slot in list(self.pending.values()):
            slot[0].set()

    def call(self, method, params=None, timeout=6):
        self.ensure()
        with self.send_lock:
            mid = self.next_id
            self.next_id += 1
            ev = threading.Event()
            self.pending[mid] = [ev, None]
            try:
                self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            except Exception:
                self.pending.pop(mid, None)
                self.drop()
                raise
        if not ev.wait(timeout):
            self.pending.pop(mid, None)
            raise TimeoutError(method)
        res = self.pending.pop(mid, [None, None])[1]
        if res is None:
            raise ConnectionError("CDP disconnesso")
        if "error" in res:
            raise RuntimeError(f"{method}: {res['error']}")
        return res.get("result", {})

    def eval(self, expr, timeout=6, gesture=False):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                           "awaitPromise": True, "userGesture": gesture},
                      timeout=timeout)
        return r.get("result", {}).get("value")

    def js(self, fn, *args, timeout=4, gesture=False):
        """Chiama una funzione JS con argomenti passati in JSON (niente stringhe montate a mano):
        js("__nav.move", "left") -> (window.__nav ? __nav.move("left") : null)."""
        obj = fn.rsplit(".", 1)[0]
        call = f"{fn}({', '.join(json.dumps(a) for a in args)})"
        return self.eval(f"(window.{obj} ? {call} : null)", timeout=timeout, gesture=gesture)

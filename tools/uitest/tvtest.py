"""Prove del dialogo tvd ↔ Chrome: la vera classe TV (tvbox.tv) guida Chromium senza schermo,
con tre canali finti (pages/canale.html: pagina bianca con un video disegnato al momento).
Telecomando, volume di sistema, palinsesti e schermo sono finti; tutto il resto è quello
che gira sulla TV: tabella dei tasti, visione, strato TV, prenotazione, sorveglianza.

    python3 tools/uitest/tvtest.py <porta DevTools> <porta server> [cartella foto]   (lo lancia uitest.sh)
"""
import base64
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import tvbox.health as health  # noqa: E402
from tvbox import keys  # noqa: E402
from tvbox.config import Config, normalize_service  # noqa: E402
from tvbox.prefs import Prefs  # noqa: E402
from tvbox.session import Session  # noqa: E402
from tvbox.tv import TV  # noqa: E402
from tvbox.actions import VOLUME_IDLE_S  # noqa: E402

cdp_port, srv_port = int(sys.argv[1]), int(sys.argv[2])
SHOTS = sys.argv[3] if len(sys.argv) > 3 else None
# canali su "localhost", launcher su "127.0.0.1": per tvd sono due siti diversi, come sulla TV
PAGE = f"http://localhost:{srv_port}/__test/canale.html"


class FakeInput:
    def __init__(self):
        self.keys = []

    def key(self, k):
        self.keys.append(k)

    def move(self, *a):
        pass

    def click(self):
        pass


cfg = Config.load([os.path.join(ROOT, "config.json")])
cfg.raw.setdefault("chrome", {})["cdp_port"] = cdp_port
cfg.raw["http_port"] = srv_port
cfg.raw.setdefault("screen", {})["video_mode"] = ""          # niente xrandr
for n in (1, 2, 3):
    sid = f"prova{n}"
    cfg.channels[sid] = cfg.services[sid] = normalize_service(sid, {
        "kind": "web", "live": True, "label": f"Prova {n}", "color": "#115e59", "group": "mediaset",
        "onair": f"test:{n}", "url": f"{PAGE}?n={n}" + ("&stall=6" if n == 3 else "")}, {})
prefs = Prefs(tempfile.mkdtemp())
prefs.set("channels", ["prova1", "prova2", "prova3"])
tv = TV(cfg, prefs, FakeInput())
tv.volume = lambda delta=0: 40 + delta
NOW = {"title": "Programma di prova", "start": int(time.time() - 600) * 1000,   # millisecondi, come epg
       "end": int(time.time() + 1200) * 1000}
tv.epg.onair = lambda: {f"test:{n}": NOW for n in (1, 2, 3)}
tv.epg.for_service = lambda sid: NOW
tv.epg.guide = lambda sid, hours=12: []
threading.Thread(target=tv.worker, daemon=True).start()

failed = 0


def js(expr):
    try:
        return tv.cdp.eval(expr, timeout=4)
    except Exception:
        return None


def until(fn, secs):
    t0 = time.monotonic()
    while time.monotonic() - t0 < secs:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def check(name, fn, secs=10):
    global failed
    ok = until(fn, secs)
    print(f"{'  ok ' if ok else ' ERR '} {name}")
    if not ok:
        failed += 1


def has(part):
    return lambda: js(f"!!(window.__tvl && __tvl.has('{part}'))")


def shot(name):
    if SHOTS:
        data = tv.cdp.call("Page.captureScreenshot", {"format": "png"}, timeout=10)["data"]
        with open(os.path.join(SHOTS, name + ".png"), "wb") as f:
            f.write(base64.b64decode(data))


def key(k):
    tv.dispatch((k,) if k not in keys.ARROWS4 else ("arrow", k, 0))


def mode():
    return keys.detect_mode(tv.context())


print("tvd ↔ Chrome")
tv.home()
check("home: stato launcher", lambda: mode() == keys.LAUNCHER)

tv.open("prova1")
check("canale: sipario subito", has("curtain"), 4)
shot("strato-sipario")
check("canale: pagina blu, non bianca", lambda: "11, 16, 32" in (js(
    "getComputedStyle(document.documentElement).backgroundColor") or ""), 4)
check("canale: video a tutto schermo", lambda: js("document.documentElement.classList.contains('__tvmaxed')"), 15)
check("canale: sipario tolto quando il video va", lambda: not has("curtain")(), 15)
check("canale: banner del programma", has("osd"), 10)
time.sleep(0.6)
shot("strato-banner")
check("canale: stato diretta", lambda: mode() == keys.LIVE_PLAYER)
check("canale: ricordato per l'accensione", lambda: prefs.get("last_channel") == "prova1")

key("up")
check("▲: barra del volume", has("vol"), 4)
key("menu")
check("MENU: pannello cambio canale", has("panel"), 6)
time.sleep(0.5)
shot("strato-pannello")
check("pannello: stato pannello", lambda: mode() == keys.PANEL)
check("pannello: canale in visione evidenziato",
      lambda: "Prova 1 · in visione" in (js("__tvl && document.getElementById('__tvlayer').shadowRoot"
                                            ".querySelector('.dch').textContent") or ""))
key("right")
key("ok")
check("OK: canale nuovo", lambda: "n=2" in tv.url() and tv.current == "prova2", 8)
check("cambio: pannello e sipario restano nella pagina nuova",
      lambda: js("!!(window.__tvl && __tvl.has('panel') && __tvl.has('curtain'))"), 4)
check("cambio: sipario tolto, pannello ancora lì",
      lambda: js("!!(window.__tvl && !__tvl.has('curtain') && __tvl.has('panel'))"), 15)
key("menu")
check("MENU: pannello chiuso", lambda: not has("panel")() and mode() == keys.LIVE_PLAYER, 4)
key("play")
check("▶❚❚: pausa con avviso", lambda: js("document.querySelector('video').paused") and has("toast")(), 4)
key("play")
check("▶❚❚: riparte", lambda: js("!document.querySelector('video').paused"), 4)

# diretta che si ferma (dopo 6 s): la sorveglianza la riapre (attese accorciate per la prova)
health.GRACE, health.STALL = 4, 4
tv.open("prova3")
stalled = tv.session
check("diretta ferma: riaperta da sola", lambda: (tv._health_tick(tv.url()) or True) and len(tv._reopens) == 1
      and tv.session is not stalled and tv.current == "prova3", 30)
# una riapertura in coda non deve scavalcare quello che l'utente ha aperto nel frattempo
old = tv.session
tv.open("prova1")
tv._reopen(old)
check("riapertura superata da un'azione dell'utente", lambda: tv.current == "prova1")

n = len(tv.services)
tv.open_episode(PAGE + "?n=9", "SERIE", "Prova · Ep. 1")
check("episodio: sipario con il titolo", lambda: "Apro Prova · Ep. 1" in (js(
    "document.getElementById('__tvlayer').shadowRoot.querySelector('.curtain').textContent") or ""), 4)
check("episodio: nessun servizio finto", lambda: len(tv.services) == n and tv.current is None)
check("episodio: video a tutto schermo", lambda: mode() == keys.PLAYER, 15)
key("menu")
check("MENU: torna alla serie", lambda: tv.url().endswith("#ms:SERIE") and tv.session is None, 6)

tv.start(Session.site(PAGE + "?n=7"))
check("sito: niente sipario", lambda: "n=7" in tv.url() and not has("curtain")(), 6)
tv.toast("Avviso di prova")
check("avviso: nello strato TV", has("toast"), 3)

# sito alla Netflix: file di locandine con la freccina, anteprime al passaggio, player con i
# suoi tasti e "Salta intro"
TEST = f"http://localhost:{srv_port}/__test/"
cfg.services["provaflix"] = normalize_service("provaflix", {
    "kind": "web", "label": "Provaflix", "url": TEST + "catalogo.html", "player_control": "keys", "hover": False}, {})
tv.open("provaflix")
check("sito: pagina del catalogo", lambda: "catalogo" in tv.url() and mode() == keys.SITE, 6)


def focused():
    return js("window.__nav && __nav.current() ? __nav.current().textContent : ''") or ""


for _ in range(5):
    key("right")
    time.sleep(0.25)
check("riquadro giallo: quinta locandina", lambda: focused() == "Titolo 5", 3)
key("right")
check("fine fila: preme la freccina e va al titolo nuovo", lambda: js("window.__paged") == 1 and focused() == "Titolo 6", 4)
check("niente anteprime al passaggio (hover: false)", lambda: js("window.__hovered") == 0)
key("ok")
check("OK: apre il titolo scelto", lambda: js("window.__opened") == "Titolo 6", 4)
key("left")
check("indietro nella fila: freccina e titolo precedente", lambda: js("window.__paged") == 2 and focused() == "Titolo 5", 4)
key("down")
check("giù: fila successiva", lambda: focused().startswith("Novità"), 3)

tv.cdp.call("Page.navigate", {"url": TEST + "player.html"})
check("player: stato video", lambda: "player" in tv.url() and mode() == keys.PLAYER, 10)
key("ok")
check("OK: preme \"Salta intro\"", lambda: js("window.__skipped") == 1, 4)
n_keys = len(tv.input.keys)
key("ok")
check("OK senza pulsanti: pausa con i tasti del sito", lambda: tv.input.keys[n_keys:] == ["space"], 3)
key("left")
check("◄: salto con i tasti del sito", lambda: tv.input.keys[-1] == "left", 3)

# sito senza video: PLAY apre la barra del volume; a tutto schermo con il player in un iframe
# di un altro sito (tvd il video non lo vede) i tasti vanno al player come da tastiera
tv.start(Session.site(TEST + "incorniciato.html"))
check("incorniciato: sito normale", lambda: "incorniciato" in tv.url() and mode() == keys.SITE, 6)
n_keys = len(tv.input.keys)
key("play")
check("PLAY senza video: barra del volume", lambda: has("vol")() and mode() == keys.VOLUME, 4)
key("up")
check("▲ nella barra: volume su, barra ancora aperta", lambda: has("vol")() and mode() == keys.VOLUME, 3)
time.sleep(2.5)
check("barra: resta a schermo più dei 2 s soliti", lambda: has("vol")() and mode() == keys.VOLUME, 1)
key("ok")
check("OK: barra chiusa, di nuovo il sito", lambda: mode() == keys.SITE and not has("vol")(), 3)
check("barra del volume: nessun tasto mandato al sito", lambda: tv.input.keys[n_keys:] == [], 1)
key("play")
time.sleep(VOLUME_IDLE_S + 0.5)
check("barra: si chiude da sola", lambda: mode() == keys.SITE, 3)
# video incorporato avviato con un clic (focus nell'iframe): PLAY è la pausa del player, non il volume
box = js("(()=>{const b=document.querySelector('iframe').getBoundingClientRect();return [b.x+b.width/2,b.y+b.height/2]})()")
tv.click_at(*box)
check("clic nel player incorporato: focus nell'iframe", lambda: js("document.activeElement.tagName") == "IFRAME", 3)
n_keys = len(tv.input.keys)
key("play")
check("PLAY con il player incorporato: barra spaziatrice, niente volume",
      lambda: tv.input.keys[n_keys:] == ["space"] and mode() == keys.SITE, 3)

tv.cdp.eval("document.querySelector('iframe').requestFullscreen(), true", timeout=4, gesture=True)
check("iframe a tutto schermo: tasti al player", lambda: mode() == keys.FULLPAGE, 6)
shot("tutto-schermo-iframe")
n_keys = len(tv.input.keys)
key("right")
key("left")
key("play")
key("ok")
check("◄ ► frecce vere, PLAY e OK barra spaziatrice",
      lambda: tv.input.keys[n_keys:] == ["right", "left", "space", "space"], 3)
key("up")
check("▲: volume della TV, non un tasto al sito", lambda: has("vol")() and len(tv.input.keys) == n_keys + 4, 3)
key("menu")
check("MENU: esce dal tutto schermo", lambda: not js("!!document.fullscreenElement") and mode() == keys.SITE, 4)

tv.home()
check("home: di nuovo il launcher", lambda: mode() == keys.LAUNCHER, 6)

print("tvd ↔ Chrome:", "tutto ok" if not failed else f"{failed} prove fallite")
os._exit(1 if failed else 0)

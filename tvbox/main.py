"""Avvio di tvd: configurazione, preferenze, TV, API, telecomando, sorveglianza di Chrome."""
import logging
import logging.handlers
import os
import signal
import threading

from . import VERSION, api
from .config import Config
from .inputdev import VirtualInput
from .prefs import Prefs
from .remote import RemoteLogic, RemoteReader
from .tv import TV
from .util import log


LOG_DIR = "/var/log/tvbox"


def setup_logging():
    """Registro in /var/log/tvbox/tvd.log (leggibile anche da admin, massimo 3 × 1 MB);
    se la cartella non c'è, solo sullo schermo/nel file della sessione come in V1."""
    fmt = logging.Formatter("%(asctime)s tvd %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    out = logging.StreamHandler()
    out.setFormatter(fmt)
    root.addHandler(out)
    if os.access(LOG_DIR, os.W_OK):
        f = logging.handlers.RotatingFileHandler(os.path.join(LOG_DIR, "tvd.log"),
                                                 maxBytes=1_000_000, backupCount=2)
        f.setFormatter(fmt)
        root.addHandler(f)


def main():
    setup_logging()
    log.info("tvbox %s", VERSION)
    cfg = Config.load()
    prefs = Prefs()
    tv = TV(cfg, prefs, VirtualInput())
    api.serve(tv, cfg.opt("http_port", 8765))
    threading.Thread(target=tv.worker, daemon=True).start()
    threading.Thread(target=tv.mediaset.prewarm, daemon=True).start()   # catalogo Mediaset pronto

    logic = RemoteLogic(cfg.opt, pointer=lambda: tv.pointer)
    tv.remote = logic
    RemoteReader(logic, tv.on_remote, cfg.opt("remote.match", ["IR Receiver"])).start()

    def bye(*_):
        log.info("uscita")
        tv.browser.kill()
        os._exit(0)
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)

    tv.display.startup()
    tv.browser.kill_stale()
    tv.watchdog()

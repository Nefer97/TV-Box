"""Avvio di tvd: configurazione, preferenze, TV, API, telecomando, sorveglianza di Chrome."""
import logging
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


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s tvd %(levelname)s %(message)s")
    log.info("tvbox %s", VERSION)
    cfg = Config.load()
    prefs = Prefs()
    tv = TV(cfg, prefs, VirtualInput())
    api.serve(tv, cfg.opt("http_port", 8765))
    threading.Thread(target=tv.worker, daemon=True).start()

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

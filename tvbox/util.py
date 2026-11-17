"""Utilità comuni: registro, scaricamenti HTTP, file JSON scritti in modo sicuro."""
import json
import logging
import os
import urllib.request

log = logging.getLogger("tvd")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER_DIR = os.path.join(BASE, "launcher")
USER_DIR = os.path.expanduser(os.environ.get("TV_USER_DIR", "~/.config/tvbox"))

DESKTOP_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/157.0 Safari/537.36")


def get_json(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "tvbox"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch(url, limit=1_500_000, timeout=8):
    """(byte, tipo) di un indirizzo, con identità da browser desktop."""
    req = urllib.request.Request(url, headers={"User-Agent": DESKTOP_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit), r.headers.get_content_type()


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    """Scrittura atomica: un file a metà (corrente staccata) non esiste mai."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as ex:
        log.warning("%s non disponibile: %s", path, ex)
        return None


def is_stream_url(u):
    """Indirizzo di un flusso video accettabile per il player di tvbox: http o https, con un host."""
    from urllib.parse import urlparse
    try:
        p = urlparse(u or "")
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.hostname)

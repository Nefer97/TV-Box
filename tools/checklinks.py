"""Verifica degli indirizzi esterni scritti a mano (catalogo dei canali, app e feed).

Se Rai, Mediaset o Discovery cambiano un indirizzo, ce ne si accorge qui invece che quando un
canale non parte sulla TV. Serve internet; non scarica video, solo pagine e piccoli file.

    python3 tools/checklinks.py          (codice 1 se qualcosa non va)
"""
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tvbox import channels as ch  # noqa: E402
from tvbox.epg import MS_NOWNEXT, WBD_GUIDE  # noqa: E402
from tvbox.mediaset import FEED  # noqa: E402
from tvbox.util import DESKTOP_UA  # noqa: E402


def get(url, limit=3_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": DESKTOP_UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(limit)
    except urllib.error.HTTPError as ex:
        return ex.code, b""
    except Exception as ex:
        return str(ex)[:60], b""


def jget(url):
    code, body = get(url)
    try:
        return code, json.loads(body)
    except ValueError:
        return code, None


def checks():
    """(nome, funzione che restituisce "" se va bene o la spiegazione del problema)"""
    out = []

    def rai_app():
        code, _ = get(ch.RAI_APP.split("?")[0])
        return "" if code == 200 else f"app RaiPlay per TV: {code}"
    out.append(("Rai: app per TV", rai_app))

    for cid, name in ch.RAI:
        def f(cid=cid, name=name):
            code, d = jget(f"https://www.raiplay.it/dirette/{cid}.json")
            if not isinstance(d, dict):
                return f"diretta: {code}"
            if d.get("channel") != name:
                return f"nome nel palinsesto diverso: {d.get('channel')!r}"
            return ""
        out.append((f"Rai: {name}", f))

    def ms_stations():
        code, d = jget(FEED + "mediaset-prod-all-stations-v2?fields=callSign&range=1-300")
        signs = {e.get("callSign") for e in (d or {}).get("entries", [])}
        missing = [n for _, n, c, _ in ch.MEDIASET_CH if c not in signs]
        return f"sigle non più nel feed: {', '.join(missing)}" if missing else ""
    out.append(("Mediaset: sigle dei canali", ms_stations))

    for cid, name, code_, slug in ch.MEDIASET_CH:
        def f(name=name, code_=code_, slug=slug):
            c1, _ = get(ch.MEDIASET.format(slug=slug, code=code_), limit=4096)
            c2, _ = get(MS_NOWNEXT.format(code=code_), limit=4096)
            bad = [f"{what}: {c}" for what, c in (("pagina della diretta", c1), ("programma in onda", c2)) if c != 200]
            return ", ".join(bad)
        out.append((f"Mediaset: {name}", f))

    def ms_catalog():
        code, d = jget(FEED + "mediaset-prod-all-series-v2?fields=guid&range=1-1")
        return "" if isinstance(d, dict) and d.get("entries") else f"catalogo serie: {code}"
    out.append(("Mediaset: catalogo fiction e serie", ms_catalog))

    def dplus():
        code, body = get("https://www.discoveryplus.com/it/it")
        if code != 200:
            return f"home di discovery+: {code}"
        page = body.decode("utf-8", "replace")
        missing = [name for _, name, c, v, _, _ in ch.DISCOVERY if f"channel/watch/{c}/{v}" not in page]
        return f"canali non più nella home di discovery+: {', '.join(missing)}" if missing else ""
    out.append(("Discovery: indirizzi dei canali", dplus))

    for _, name, _, _, env, _ in ch.DISCOVERY:
        if not env:
            continue
        def f(env=env):
            code, d = jget(WBD_GUIDE.format(env=env))
            return "" if isinstance(d, dict) else f"guida TV: {code}"
        out.append((f"Discovery: guida di {name}", f))
    return out


def main():
    items = checks()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda it: (it[0], it[1]()), items))
    bad = 0
    for name, err in results:
        print(f"{'  ok ' if not err else ' ERR '} {name}" + (f" — {err}" if err else ""))
        bad += bool(err)
    print("indirizzi esterni:", "tutti a posto" if not bad else f"{bad} da controllare")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

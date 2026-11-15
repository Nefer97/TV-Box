"""Palinsesti: il programma in onda sui canali, nello stesso formato per tutti.

Ogni canale in config.json ha "onair": "<fonte>:<codice>":
    rai:<nome canale>   https://www.raiplay.it/palinsesto/onAir.json
    ms:<sigla>          https://static3.mediasetplay.mediaset.it/apigw/nownext/<sigla>.json
    wbd:<ambiente>      Guida TV pubblica di Warner Bros. Discovery (Real Time, DMAX, Nove)

Formato: {"title", "desc", "start", "end" (millisecondi), "image", "image_big"}
Le funzioni parse_* lavorano sui dati già scaricati: si provano con i test.
"""
import calendar
import re
import threading
import time

from .util import get_json, log

RAI_ONAIR = "https://www.raiplay.it/palinsesto/onAir.json"
MS_NOWNEXT = "https://static3.mediasetplay.mediaset.it/apigw/nownext/{code}.json"
WBD_GUIDE = ("https://public.aurora.enhanced.live/site/page/guida-tv/?include=default"
             "&filter%5Benvironment%5D={env}&v=2")


# ---------- Rai ----------
def parse_rai(d, now=None):
    """{"rai:Rai 1": {...}, ...} dal file onAir.json."""
    now = time.time() if now is None else now
    lt = time.localtime(now)
    out = {}
    for c in d.get("on_air", []):
        ci = c.get("currentItem") or {}
        img = (ci.get("images") or {}).get("landscape") or ci.get("image") or ""
        dur = re.match(r"(\d+):(\d+)", ci.get("duration") or "")
        hour = re.match(r"(\d+):(\d+)", ci.get("hour") or "")
        start = end = 0
        if hour:
            st = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, int(hour.group(1)),
                              int(hour.group(2)), 0, 0, 0, -1))
            if st > now + 60:
                st -= 86400                              # iniziato ieri sera
            start = int(st * 1000)
            end = start + ((int(dur.group(1)) * 60 + int(dur.group(2))) * 60000 if dur else 0)
        crop = (lambda size: f"https://www.raiplay.it/cropgd/{size}{img}" if img.startswith("/") else "")
        out["rai:" + c.get("channel", "")] = {
            "title": (ci.get("program") or {}).get("name") or ci.get("name") or "",
            "desc": ci.get("description") or "", "start": start, "end": end,
            "image": crop("480x270"), "image_big": crop("1280x720")}
    return out


# ---------- Mediaset ----------
def parse_mediaset(d, now=None):
    now = time.time() if now is None else now
    r = d.get("response") or {}
    cl = r.get("currentListing") or {}
    # il file viene aggiornato in ritardo: se il programma "attuale" è finito, è il successivo
    if (cl.get("endTime") or 0) < now * 1000 and r.get("nextListing"):
        cl = r["nextListing"]
    p = cl.get("program") or {}
    img, best, big, bw = "", 0, "", 0
    for k, v in (p.get("thumbnails") or {}).items():
        w = v.get("width") or 0
        if "keyframe" not in k or not v.get("url"):
            continue
        if not img or (360 <= w < best) or best < 360 < w:     # scheda: la più piccola da 360 px
            img, best = v["url"], w
        if bw < w <= 1920:                                     # salvaschermo: la più grande
            big, bw = v["url"], w
    return {"title": cl.get("mediasetlisting$epgTitle") or p.get("title") or "",
            "desc": cl.get("description") or p.get("description") or "",
            "start": cl.get("startTime") or 0, "end": cl.get("endTime") or 0,
            "image": img, "image_big": big or img}


# ---------- Warner Bros. Discovery ----------
def wbd_programs(d):
    """Tutti i programmi del blocco "epgBlock" della Guida TV."""
    progs = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "epgBlock":
                for ch in o.get("channels") or []:
                    for day in ch.get("days") or []:
                        progs.extend(p for p in day.get("programs") or [] if p.get("start_dt"))
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    return progs


def wbd_now(progs, now=None):
    now = time.time() if now is None else now
    for p in progs:
        try:
            # orari in UTC ("+00:00"): calendar.timegm non dipende da fuso e ora legale
            st = calendar.timegm(time.strptime(p["start_dt"][:19], "%Y-%m-%dT%H:%M:%S"))
            en = calendar.timegm(time.strptime(p["end_dt"][:19], "%Y-%m-%dT%H:%M:%S"))
        except (KeyError, ValueError):
            continue
        if st <= now < en and (p.get("title") or p.get("show_name")):
            show, ep = p.get("show_name") or "", p.get("title") or ""
            desc = p.get("description") or ""
            if show and ep and ep != show:
                desc = f"{ep}. {desc}" if desc else ep
            img = p.get("show_image") or ""
            return {"title": show or ep, "desc": desc, "start": int(st * 1000), "end": int(en * 1000),
                    "image": img, "image_big": img}
    return {}


class EPG:
    """Programmi in onda per tutti i canali, aggiornati al massimo una volta al minuto."""

    def __init__(self, services):
        self.services = services
        self.lock = threading.Lock()
        self.t = 0.0
        self.data = {}
        self.wbd = {}                       # ambiente -> (istante, programmi): si scarica ogni 30 min

    def keys(self):
        return {s["onair"] for s in self.services.values() if s.get("onair")}

    def onair(self):
        with self.lock:
            if time.monotonic() - self.t < 60:
                return self.data
            data, keys = dict(self.data), self.keys()
            if any(k.startswith("rai:") for k in keys):
                try:
                    data.update(parse_rai(get_json(RAI_ONAIR)))
                except Exception as ex:
                    log.warning("palinsesto Rai non disponibile: %s", ex)
            for k in keys:
                src, _, code = k.partition(":")
                try:
                    if src == "ms":
                        data[k] = parse_mediaset(get_json(MS_NOWNEXT.format(code=code)))
                    elif src == "wbd":
                        c = self.wbd.get(code)
                        if not c or time.monotonic() - c[0] > 1800:
                            c = self.wbd[code] = (time.monotonic(),
                                                  wbd_programs(get_json(WBD_GUIDE.format(env=code), timeout=10)))
                        data[k] = wbd_now(c[1])
                except Exception as ex:
                    log.warning("palinsesto %s non disponibile: %s", k, ex)
            self.t, self.data = time.monotonic(), data
            return data

    def for_service(self, sid):
        s = self.services.get(sid) or {}
        return self.onair().get(s.get("onair") or "", {}) if s.get("onair") else {}

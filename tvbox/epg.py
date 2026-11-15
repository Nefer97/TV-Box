"""Palinsesti: il programma in onda sui canali, nello stesso formato per tutti.

Ogni canale in config.json ha "onair": "<fonte>:<codice>":
    rai:<nome canale>   https://www.raiplay.it/palinsesto/onAir.json
    ms:<sigla>          https://static3.mediasetplay.mediaset.it/apigw/nownext/<sigla>.json
    wbd:<ambiente>      Guida TV pubblica di Warner Bros. Discovery (Real Time, DMAX, Nove)

Formato: {"title", "desc", "start", "end" (millisecondi), "image", "image_big"}
Le funzioni parse_* lavorano sui dati già scaricati: si provano con i test.

Guida TV (programmi delle prossime ore), stesse fonti in versione "giornata":
    rai:  https://www.raiplay.it/palinsesto/app/<rai-1>/<gg-mm-aaaa>.json   (oggi e domani)
    ms:   feed "all listings" di Mediaset con una finestra di tempo
    wbd:  la stessa Guida TV di sopra (contiene già più giorni)
"""
import calendar
import re
import threading
import time

from .util import get_json, log

RAI_ONAIR = "https://www.raiplay.it/palinsesto/onAir.json"
MS_NOWNEXT = "https://static3.mediasetplay.mediaset.it/apigw/nownext/{code}.json"
RAI_DAY = "https://www.raiplay.it/palinsesto/app/{slug}/{day}.json"
MS_LISTINGS = ("https://feed.entertainment.tv.theplatform.eu/f/PR1GhC/mediaset-prod-all-listings-v2"
               "?byListingTime={start}~{end}&byCallSign={code}")
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


# ---------- Guida TV: liste di programmi ----------
def rai_slug(name):
    """ "Rai 1" -> "rai-1", "Rai News 24" -> "rai-news-24" """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse_rai_day(d):
    out = []
    for e in d.get("events") or []:
        try:
            day, hour = e["date"].replace("/", "-"), e["hour"]      # "15/11/2026"
            st = time.mktime(time.strptime(f"{day} {hour}", "%d-%m-%Y %H:%M"))
        except (KeyError, ValueError):
            continue
        dur = re.match(r"(\d+):(\d+)(?::(\d+))?", e.get("duration") or "")
        mins = int(dur.group(1)) * 60 + int(dur.group(2)) if dur else 0
        img = e.get("image") or ""
        crop = (lambda size: f"https://www.raiplay.it/cropgd/{size}{img}" if img.startswith("/") else "")
        title = (e.get("program") or {}).get("name") or e.get("name") or ""
        ep = e.get("episode_title") or ""
        desc = e.get("description") or ""
        if ep and ep not in title and not ep.lower().startswith("puntata del"):
            desc = f"{ep}. {desc}" if desc else ep
        out.append({"title": title, "desc": desc, "start": int(st * 1000), "end": int((st + mins * 60) * 1000),
                    "image": crop("480x270"), "image_big": crop("1280x720")})
    return out


def _ms_images(p):
    img, best, big, bw = "", 0, "", 0
    for k, v in (p.get("thumbnails") or {}).items():
        w = v.get("width") or 0
        if "keyframe" not in k or not v.get("url"):
            continue
        if not img or (360 <= w < best) or best < 360 < w:
            img, best = v["url"], w
        if bw < w <= 1920:
            big, bw = v["url"], w
    return img, big or img


def parse_mediaset_listings(d):
    out = []
    for ent in d.get("entries") or []:
        for l in ent.get("listings") or []:
            p = l.get("program") or {}
            img, big = _ms_images(p)
            title = l.get("mediasetlisting$epgTitle") or p.get("title") or ""
            ep = p.get("title") or ""
            desc = l.get("description") or p.get("description") or ""
            if ep and ep != title:
                desc = f"{ep}. {desc}" if desc else ep
            out.append({"title": title, "desc": desc, "start": l.get("startTime") or 0,
                        "end": l.get("endTime") or 0, "image": img, "image_big": big})
    return sorted(out, key=lambda x: x["start"])


def wbd_list(progs):
    out = []
    for p in progs:
        try:
            st = calendar.timegm(time.strptime(p["start_dt"][:19], "%Y-%m-%dT%H:%M:%S"))
            en = calendar.timegm(time.strptime(p["end_dt"][:19], "%Y-%m-%dT%H:%M:%S"))
        except (KeyError, ValueError):
            continue
        show, ep = p.get("show_name") or "", p.get("title") or ""
        desc = p.get("description") or ""
        if show and ep and ep != show:
            desc = f"{ep}. {desc}" if desc else ep
        img = p.get("show_image") or ""
        out.append({"title": show or ep, "desc": desc, "start": int(st * 1000), "end": int(en * 1000),
                    "image": img, "image_big": img})
    return sorted(out, key=lambda x: x["start"])


def upcoming(progs, now=None, hours=12):
    """Dal programma in onda alle prossime ore, senza doppioni."""
    now_ms = (time.time() if now is None else now) * 1000
    seen, out = set(), []
    for p in sorted(progs, key=lambda x: x["start"]):
        if p["end"] <= now_ms or p["start"] > now_ms + hours * 3600_000 or p["start"] in seen:
            continue
        seen.add(p["start"])
        out.append(p)
    return out


class EPG:
    """Programmi in onda per tutti i canali, aggiornati al massimo una volta al minuto."""

    def __init__(self, services):
        self.services = services
        self.lock = threading.Lock()
        self.t = 0.0
        self.data = {}
        self.wbd = {}                       # ambiente -> (istante, programmi): si scarica ogni 30 min
        self.guides = {}                    # "rai:Rai 1" -> (istante, programmi della giornata)

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

    def guide(self, sid, hours=12):
        """Programmi del canale dal momento attuale alle prossime ore (si riscarica ogni 15 min)."""
        s = self.services.get(sid) or {}
        key = s.get("onair") or ""
        src, _, code = key.partition(":")
        with self.lock:
            c = self.guides.get(key)
            if not c or time.monotonic() - c[0] > 900:
                progs = []
                try:
                    if src == "rai":
                        for d in (0, 1):                    # oggi e domani (la sera va oltre mezzanotte)
                            day = time.strftime("%d-%m-%Y", time.localtime(time.time() + d * 86400))
                            progs += parse_rai_day(get_json(RAI_DAY.format(slug=rai_slug(code), day=day)))
                    elif src == "ms":
                        now = int(time.time())
                        progs = parse_mediaset_listings(get_json(MS_LISTINGS.format(
                            start=(now - 4 * 3600) * 1000, end=(now + 16 * 3600) * 1000, code=code), timeout=10))
                    elif src == "wbd":
                        w = self.wbd.get(code)
                        if not w or time.monotonic() - w[0] > 1800:
                            w = self.wbd[code] = (time.monotonic(),
                                                  wbd_programs(get_json(WBD_GUIDE.format(env=code), timeout=10)))
                        progs = wbd_list(w[1])
                except Exception as ex:
                    log.warning("guida %s non disponibile: %s", key, ex)
                    if c:
                        return upcoming(c[1], hours=hours)
                c = self.guides[key] = (time.monotonic(), progs)
        return upcoming(c[1], hours=hours)

    def for_service(self, sid):
        s = self.services.get(sid) or {}
        return self.onair().get(s.get("onair") or "", {}) if s.get("onair") else {}

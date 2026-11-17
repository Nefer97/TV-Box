"""Prove delle parti delicate di tvd, senza Chrome, telecomando né rete.

    python3 -m unittest discover -s tests -v
"""
import calendar
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tvbox import keys  # noqa: E402
from tvbox.config import Config, normalize_service  # noqa: E402
from tvbox.display import parse_xrandr, scale_for  # noqa: E402
from tvbox.epg import (parse_mediaset, parse_mediaset_listings, parse_rai, parse_rai_day, rai_slug,  # noqa: E402
                       upcoming, wbd_list, wbd_now, wbd_programs)
from tvbox.prefs import Prefs  # noqa: E402
from tvbox.remote import RemoteLogic  # noqa: E402
from tvbox.sites import normalize_url  # noqa: E402
from tvbox.health import Watch, may_reopen  # noqa: E402
from tvbox.mediaset import episodes_of, is_episode_url, parse_series  # noqa: E402
from tvbox.session import Session  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def wjson(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def opts(**over):
    return lambda path, default=None: over.get(path.split(".")[-1], default)


class RemoteTest(unittest.TestCase):
    def setUp(self):
        self.pointer = False
        self.r = RemoteLogic(opts(), pointer=lambda: self.pointer)

    def press(self, key, t0, dur, step=0.11):
        """Pressione con le ripetizioni del ricevitore (circa ogni 110 ms)."""
        ev = self.r.handle(key, 1, t0)
        t = t0 + step
        while t < t0 + dur:
            ev += self.r.handle(key, 2, t)
            ev += self.r.tick(t)
            t += step
        ev += self.r.tick(t0 + dur)
        ev += self.r.handle(key, 0, t0 + dur)
        return ev

    def test_pressione_breve_un_passo(self):
        self.assertEqual(self.press("right", 10, 0.4), [("arrow", "right", 0)])

    def test_doppione_ignorato(self):
        ev = self.press("right", 10, 0.15) + self.press("right", 10.25, 0.3)
        self.assertEqual(ev, [("arrow", "right", 0)])

    def test_due_pressioni_distinte(self):
        ev = self.press("right", 10, 0.15) + self.press("right", 10.6, 0.15)
        self.assertEqual(len(ev), 2)

    def test_tenuta_ripete_dopo_600ms(self):
        ev = self.press("down", 10, 1.5)
        self.assertEqual(ev[0], ("arrow", "down", 0))
        self.assertTrue(len(ev) >= 4, ev)
        self.assertTrue(all(e[0] == "arrow" for e in ev))

    def test_menu_breve_e_lungo(self):
        self.assertEqual(self.press("menu", 10, 0.2), [("menu",)])
        self.assertEqual(self.press("menu", 20, 1.2), [("menu_long",)])

    def test_ok_lungo_solo_dopo_1500ms(self):
        self.assertEqual(self.press("play", 10, 1.0), [("ok",)])          # bianco: centrale = OK
        self.assertEqual(self.press("play", 20, 1.7), [("ok_long",)])

    def test_alluminio(self):
        self.press("enter", 10, 0.1)
        self.assertEqual(self.press("play", 20, 0.1), [("play",)])

    def test_puntatore(self):
        self.pointer = True
        ev = self.press("left", 10, 1.0)
        self.assertEqual(ev[0], ("arrow", "left", 0))
        self.assertTrue(any(e[0] == "pointer" for e in ev))


class KeysTest(unittest.TestCase):
    def mode(self, **kw):
        return keys.detect_mode(keys.Context(**kw))

    def test_stati(self):
        self.assertEqual(self.mode(on_launcher=True), keys.LAUNCHER)
        self.assertEqual(self.mode(panel=True, on_launcher=False), keys.PANEL)
        self.assertEqual(self.mode(pointer=True), keys.POINTER)
        self.assertEqual(self.mode(kind="hbbtv", live=True), keys.LIVE_TV)
        self.assertEqual(self.mode(kind="web", live=True, player=True), keys.LIVE_PLAYER)
        self.assertEqual(self.mode(kind="web", live=True, player=False), keys.LIVE_SITE)
        self.assertEqual(self.mode(kind="hbbtv"), keys.TVAPP_HBBTV)
        self.assertEqual(self.mode(kind="tvapp"), keys.TVAPP)
        self.assertEqual(self.mode(kind="web", player=True), keys.PLAYER)
        self.assertEqual(self.mode(kind="web"), keys.SITE)
        self.assertEqual(self.mode(kind="web", assist=False), keys.WEB)
        self.assertEqual(self.mode(kind="web", fullscreen=True), keys.FULLPAGE)
        self.assertEqual(self.mode(kind="web", frame_player=True), keys.FULLPAGE)
        self.assertEqual(self.mode(kind="web", live=True, frame_player=True), keys.LIVE_SITE)
        self.assertEqual(self.mode(kind="web", player=True, fullscreen=True), keys.PLAYER)
        self.assertEqual(self.mode(kind="hbbtv", fullscreen=True), keys.TVAPP_HBBTV)
        self.assertEqual(self.mode(kind="web", live=True, fullscreen=True), keys.LIVE_SITE)
        self.assertEqual(self.mode(kind="web", volume=True), keys.VOLUME)
        self.assertEqual(self.mode(panel=True, volume=True), keys.PANEL)

    def test_schermo_intero_con_player_del_sito(self):
        m = keys.FULLPAGE
        self.assertEqual(keys.action_for(m, "left"), "key_arrow")
        self.assertEqual(keys.action_for(m, "up"), "player_volume")
        self.assertEqual(keys.action_for(m, "ok"), "key_space")
        self.assertEqual(keys.action_for(m, "play"), "key_space")
        self.assertEqual(keys.action_for(m, "menu_long"), "home")

    def test_play_nei_siti_apre_il_volume(self):
        self.assertEqual(keys.action_for(keys.SITE, "play"), "site_play")
        self.assertEqual(keys.action_for(keys.VOLUME, "up"), "volume_step")
        for k in ("ok", "menu", "play", "left"):
            self.assertEqual(keys.action_for(keys.VOLUME, k), "volume_close")
        self.assertEqual(keys.action_for(keys.VOLUME, "menu_long"), "home")

    def test_menu_sulle_dirette_apre_il_pannello(self):
        for m in (keys.LIVE_TV, keys.LIVE_PLAYER, keys.LIVE_SITE):
            self.assertEqual(keys.action_for(m, "menu"), "panel_open")

    def test_pannello(self):
        self.assertEqual(keys.action_for(keys.PANEL, "up"), "panel_volume")
        self.assertEqual(keys.action_for(keys.PANEL, "left"), "panel_move")
        self.assertIsNone(keys.action_for(keys.PANEL, "ok_long"))
        self.assertEqual(keys.action_for(keys.PANEL, "menu_long"), "home")

    def test_ogni_stato_ha_tutti_i_tasti(self):
        for m in keys.KEYMAP:
            for k in ("up", "down", "left", "right", "ok", "menu", "play"):
                self.assertIsNotNone(keys.action_for(m, k), (m, k))

    def test_azioni_esistono_in_tv(self):
        src = ""
        for name in ("tv.py", "actions.py", "panel.py", "sleep.py", "health.py"):   # la TV e le sue parti
            with open(os.path.join(ROOT, "tvbox", name), encoding="utf-8") as f:
                src += f.read()
        acts = {a for t in list(keys.KEYMAP.values()) + [keys.COMMON] for a in t.values() if a}
        for a in acts:
            self.assertIn(f"def {a}(", src, a)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config.load([os.path.join(ROOT, "config.json")])

    def test_identita_risolte(self):
        self.assertIn("HbbTV/1.5.1", self.cfg.services["rai1"]["ua"])
        self.assertIn("Leanback", self.cfg.services["youtube"]["ua"])
        self.assertIsNone(self.cfg.services["canale5"]["ua"])

    def test_tipi(self):
        s = self.cfg.services
        self.assertEqual(s["rai1"]["back"], "tvkey")
        self.assertFalse(s["youtube"]["assist"])
        self.assertTrue(s["la7"]["assist"])
        self.assertEqual(s["altri"]["kind"], "page")
        self.assertEqual(s["canale5"]["block"], ["trackers"])

    def test_siti_con_player_esigente(self):
        n = self.cfg.services["netflix"]
        self.assertEqual((n["player_control"], n["hover"]), ("keys", False))
        la7 = self.cfg.services["la7"]
        self.assertEqual((la7["player_control"], la7["hover"]), ("video", True))     # di serie
        self.assertEqual(keys.action_for(keys.PLAYER, "ok"), "player_ok")              # "Salta intro" o pausa

    def test_canali_in_diretta(self):
        sel = ["rai1", "rai2", "rai2", "inesistente", "canale5"]
        self.assertEqual(self.cfg.live_channels(sel), ["rai1", "rai2", "canale5"])   # niente doppioni

    def test_catalogo(self):
        c = self.cfg.channels
        self.assertGreaterEqual(len(c), 35)
        self.assertEqual(c["rai4"]["kind"], "hbbtv")
        self.assertIn("rai4.json", c["rai4"]["url"])
        self.assertEqual(c["iris"]["onair"], "ms:KI")
        self.assertEqual(c["hgtv"]["onair"], "wbd:hgtvit")
        self.assertNotIn("onair", c["giallo"])
        self.assertTrue(all(s["live"] for s in c.values()))

    def test_sezione_canali_della_home(self):
        ui = self.cfg.ui(["iris", "rai1"])
        live = [s for s in ui["sections"] if s.get("channels")][0]
        self.assertEqual(live["items"], ["iris", "rai1"])
        self.assertIn("la5", ui["services"])

    def test_ui_per_il_launcher(self):
        ui = self.cfg.ui()
        self.assertIn("sections", ui)
        self.assertEqual(ui["services"]["rai1"]["label"], "Rai 1")
        self.assertNotIn("ua", ui["services"]["rai1"])

    def test_tipo_sconosciuto(self):
        self.assertEqual(normalize_service("x", {"kind": "boh"}, {})["kind"], "web")

    def test_opt(self):
        self.assertEqual(self.cfg.opt("remote.long_press_ms"), 800)
        self.assertEqual(self.cfg.opt("non.esiste", 5), 5)


class PrefsTest(unittest.TestCase):
    def test_file_nuovo(self):
        with tempfile.TemporaryDirectory() as d:
            p = Prefs(d)
            self.assertEqual(p.get("channels")[:3], ["rai1", "rai2", "rai3"])
            self.assertTrue(os.path.exists(os.path.join(d, "prefs.json")))

    def test_dalla_versione_2(self):
        """V3 -> V4: un canale nascosto con "hidden" esce dalla scelta dei canali."""
        with tempfile.TemporaryDirectory() as d:
            wjson(os.path.join(d, "prefs.json"), {"version": 2, "hidden": ["rai2", "la7"],
                                                 "channels": ["rai1", "rai2", "canale5"]})
            p = Prefs(d)
            self.assertEqual(p.get("channels"), ["rai1", "canale5"])
            self.assertEqual(p.get("hidden"), ["la7"])
            self.assertEqual(Prefs(d).get("channels"), ["rai1", "canale5"])   # salvato

    def test_scelta_vuota(self):
        with tempfile.TemporaryDirectory() as d:
            wjson(os.path.join(d, "prefs.json"), {"version": 3, "channels": []})
            self.assertTrue(Prefs(d).get("channels"))                      # mai senza canali

    def test_file_rovinato(self):
        with tempfile.TemporaryDirectory() as d:
            wjson(os.path.join(d, "prefs.json"), {"sites": 3, "screen": {"mode": 7}})
            p = Prefs(d)
            self.assertEqual(p.get("sites"), [])
            self.assertEqual(p.get("screen")["mode"], "auto")

    def test_update_e_rilettura(self):
        with tempfile.TemporaryDirectory() as d:
            Prefs(d).update("hidden", lambda h: h + ["la7", "rai2"])
            self.assertEqual(Prefs(d).get("hidden"), ["la7"])            # i canali non si nascondono


class SitesTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_url("la7.it"), "https://la7.it")
        self.assertEqual(normalize_url(" http://x.it/a "), "http://x.it/a")
        self.assertIsNone(normalize_url("ciao"))
        self.assertIsNone(normalize_url("ftp://x.it"))
        self.assertIsNone(normalize_url(""))


class DisplayTest(unittest.TestCase):
    XR = ("Screen 0: minimum 320 x 200, current 1280 x 720, maximum 8192 x 8192\n"
          "VGA-1 connected primary 1280x720+0+0 (normal) 0mm x 0mm\n"
          "   1280x720      60.00*+\n   1360x768      59.80  \n   1024x768      60.00  \n"
          "DVI-D-1 disconnected (normal left inverted right x axis y axis)\n")

    def test_parse(self):
        out, cur, pref, modes = parse_xrandr(self.XR)
        self.assertEqual((out, cur, pref), ("VGA-1", (1280, 720), "1280x720"))
        self.assertEqual(modes, ["1280x720", "1360x768", "1024x768"])

    def test_ingrandimento(self):
        self.assertEqual(scale_for(720), 1.0)
        self.assertEqual(scale_for(768), 1.0)           # 1.07 renderebbe tutto sfocato
        self.assertEqual(scale_for(1080), 1.5)


class EpgTest(unittest.TestCase):
    def test_rai(self):
        now = time.mktime((2026, 11, 15, 20, 40, 0, 0, 0, -1))
        d = {"on_air": [{"channel": "Rai 1", "currentItem": {
            "name": "Puntata", "program": {"name": "UEFA Nations League"}, "hour": "20:30",
            "duration": "02:50", "description": "Italia-Belgio",
            "images": {"landscape": "/img/x.jpg"}}}]}
        r = parse_rai(d, now)["rai:Rai 1"]
        self.assertEqual(r["title"], "UEFA Nations League")
        self.assertEqual((r["end"] - r["start"]) // 60000, 170)
        self.assertTrue(r["image"].startswith("https://www.raiplay.it/cropgd/480x270/img"))

    def test_rai_iniziato_ieri(self):
        now = time.mktime((2026, 11, 15, 0, 30, 0, 0, 0, -1))
        d = {"on_air": [{"channel": "Rai 1", "currentItem": {"name": "Film", "hour": "23:40",
                                                             "duration": "02:00"}}]}
        self.assertLess(parse_rai(d, now)["rai:Rai 1"]["start"], now * 1000)

    def test_mediaset_ritardo(self):
        now = 1_000_000
        d = {"response": {"currentListing": {"endTime": (now - 60) * 1000, "program": {"title": "Vecchio"}},
                          "nextListing": {"startTime": (now - 60) * 1000, "endTime": (now + 600) * 1000,
                                          "mediasetlisting$epgTitle": "Tg5", "program": {}}}}
        self.assertEqual(parse_mediaset(d, now)["title"], "Tg5")

    def test_wbd(self):
        d = {"blocks": [{"type": "epgBlock", "channels": [{"days": [{"programs": [
            {"start_dt": "2026-11-15T19:00:00+00:00", "end_dt": "2026-11-15T20:00:00+00:00",
             "show_name": "Vado a vivere nel bosco", "title": "Episodio 3"}]}]}]}]}
        now = calendar.timegm(time.strptime("2026-11-15T19:30:00", "%Y-%m-%dT%H:%M:%S"))
        r = wbd_now(wbd_programs(d), now)
        self.assertEqual(r["title"], "Vado a vivere nel bosco")
        self.assertTrue(r["desc"].startswith("Episodio 3"))


class GuideTest(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(rai_slug("Rai 1"), "rai-1")
        self.assertEqual(rai_slug("Rai News 24"), "rai-news-24")

    def test_rai_giornata(self):
        d = {"events": [{"date": "15/11/2026", "hour": "20:30", "duration": "02:50:00", "name": "Partita",
                         "program": {"name": "UEFA Nations League"}, "image": "/dl/img/x.jpg"},
                        {"date": "15/11/2026", "hour": "23:20", "duration": "00:05:00", "name": "TG1 Sera",
                         "program": {"name": "Tg1"}, "episode_title": "Puntata del 15/11/2026"}]}
        p = parse_rai_day(d)
        self.assertEqual([x["title"] for x in p], ["UEFA Nations League", "Tg1"])
        self.assertEqual((p[0]["end"] - p[0]["start"]) // 60000, 170)
        self.assertEqual(p[1]["desc"], "")                       # "Puntata del…" non serve
        self.assertTrue(p[0]["image"].endswith("/cropgd/480x270/dl/img/x.jpg"))

    def test_mediaset_elenco(self):
        d = {"entries": [{"listings": [
            {"startTime": 2000, "endTime": 3000, "mediasetlisting$epgTitle": "Tg5", "program": {"title": "Tg5"}},
            {"startTime": 1000, "endTime": 2000, "mediasetlisting$epgTitle": "Serie", "program": {"title": "Episodio 3"}}]}]}
        p = parse_mediaset_listings(d)
        self.assertEqual([x["title"] for x in p], ["Serie", "Tg5"])
        self.assertEqual(p[0]["desc"], "Episodio 3")

    def test_prossime_ore(self):
        h = 3600_000
        progs = [{"start": 0, "end": h}, {"start": h, "end": 2 * h}, {"start": 2 * h, "end": 3 * h},
                 {"start": h, "end": 2 * h}, {"start": 20 * h, "end": 21 * h}]
        out = upcoming(progs, now=1.5 * 3600, hours=4)
        self.assertEqual([p["start"] for p in out], [h, 2 * h])     # niente passati, doppioni, troppo lontani

    def test_wbd_elenco(self):
        progs = [{"start_dt": "2026-11-15T20:00:00+00:00", "end_dt": "2026-11-15T21:00:00+00:00", "show_name": "B"},
                 {"start_dt": "2026-11-15T19:00:00+00:00", "end_dt": "2026-11-15T20:00:00+00:00", "show_name": "A"}]
        self.assertEqual([p["title"] for p in wbd_list(progs)], ["A", "B"])


class LiveKeysTest(unittest.TestCase):
    def test_frecce_sulle_dirette(self):
        for m in (keys.LIVE_TV, keys.LIVE_PLAYER):
            self.assertEqual(keys.action_for(m, "left"), "panel_step")
            self.assertEqual(keys.action_for(m, "up"), "player_volume")
        self.assertEqual(keys.action_for(keys.PLAYER, "left"), "player_seek")   # video normali: salti


class MediasetTest(unittest.TestCase):
    def test_serie(self):
        s = parse_series({"guid": "SE1", "title": "Terra amara", "tags": [{"scheme": "category", "title": "Fiction"}],
                          "thumbnails": {"image_vertical-264x396": {"url": "https://x/p.jpg"}},
                          "seriesTvSeasons": [{"id": "http://s/2", "guid": "ST2", "tvSeasonNumber": 2},
                                              {"id": "http://s/1", "guid": "ST1", "tvSeasonNumber": 1}],
                          "mediasetprogram$pageUrl": "//mediasetinfinity.mediaset.it/fiction/terraamara_SE1"})
        self.assertEqual(s["poster"], "https://x/p.jpg")
        self.assertEqual([x["n"] for x in s["seasons"]], [1, 2])
        self.assertEqual(s["category"], "Fiction")
        self.assertTrue(s["url"].startswith("https://"))

    def test_episodi_gratis_in_ordine(self):
        ep = lambda n, day, rights, url="//mediasetinfinity.mediaset.it/video/x/ep_F1": {   # noqa: E731
            "guid": f"F{n}{day}", "tvSeasonEpisodeNumber": n, "title": f"Ep {n}", "mediasetprogram$videoPageUrl": url,
            "mediasetprogram$channelsRights": rights,
            "mediasetprogram$publishInfo": {"last_published": f"2026-11-{day:02d}T21:00:00Z"}}
        eps = episodes_of([ep(7, 1, ["AVOD"]), ep(8, 8, ["AVOD"]), ep(8, 15, ["AVOD"]), ep(9, 16, ["SVOD"]),
                           ep(None, 2, ["AVOD"])])
        self.assertEqual([(e["n"], e["id"]) for e in eps], [(8, "F815"), (8, "F88"), (7, "F71")])
        self.assertTrue(eps[0]["url"].startswith("https://mediasetinfinity"))

    def test_programma_senza_numeri(self):
        """Talk show e programmi quotidiani: puntate intere per data, niente clip."""
        v = lambda g, day, dur: {"guid": g, "title": g, "mediasetprogram$duration": dur,     # noqa: E731
                                 "mediasetprogram$videoPageUrl": "//mediasetinfinity.mediaset.it/video/x/" + g,
                                 "mediasetprogram$channelsRights": ["AVOD"],
                                 "mediasetprogram$publishInfo": {"last_published": f"2026-11-{day:02d}T21:00:00Z"}}
        eps = episodes_of([v("clip", 15, 180), v("p1", 8, 5400), v("p2", 14, 5300)])
        self.assertEqual([e["id"] for e in eps], ["p2", "p1"])

    def test_solo_titoli_con_qualcosa_da_vedere(self):
        from tvbox.mediaset import Mediaset
        m = Mediaset(None)
        s = lambda g: {"id": g, "title": g, "current": None, "seasons": [{"id": "season-" + g, "guid": g}]}  # noqa: E731
        m.playable_cache = {"season-a": (time.monotonic(), True), "season-b": (time.monotonic(), False)}
        self.assertTrue(m.known(s("a")))
        self.assertFalse(m.known(s("b")))
        self.assertIsNone(m.known(s("c")))                                  # non ancora controllato

    def test_indirizzo_episodio(self):
        self.assertTrue(is_episode_url("https://mediasetinfinity.mediaset.it/video/x/ep_F1"))
        self.assertFalse(is_episode_url("https://evil.it/video/x"))
        self.assertFalse(is_episode_url("https://mediasetinfinity.mediaset.it/diretta/canale5"))


class HealthTest(unittest.TestCase):
    def test_partenza_e_avanzamento(self):
        w = Watch("canale5", 0)
        self.assertFalse(w.step({"t": None}, 10))                # ancora in partenza
        for k in range(30, 120, 2):
            self.assertFalse(w.step({"t": k}, k))                # avanza: tutto bene

    def test_fermo_una_volta_sola(self):
        w = Watch("canale5", 0)
        w.step({"t": 5}, 26)
        self.assertFalse(w.step({"t": 5}, 40))                   # fermo da 14 s: si aspetta
        self.assertTrue(w.step({"t": 5}, 47))                    # fermo da 21 s: bloccato
        self.assertFalse(w.step({"t": 5}, 60))                   # già gestito

    def test_pausa_voluta(self):
        w = Watch("canale5", 0)
        for k in range(26, 200, 2):
            self.assertFalse(w.step({"t": 5, "user": True}, k))

    def test_nessun_video(self):
        w = Watch("canale5", 0)
        w.step({}, 26)
        self.assertTrue(w.step({}, 50))                          # nero senza video: bloccato

    def test_riaperture(self):
        ok, h = may_reopen([0, 100, 200], 300)
        self.assertFalse(ok)
        ok, h = may_reopen([0, 100, 200], 700)
        self.assertTrue(ok)
        self.assertEqual(h, [200])


class SessionTest(unittest.TestCase):
    """Le regole di "cosa si sta guardando" (session.py)."""

    def setUp(self):
        self.cfg = Config.load([os.path.join(ROOT, "config.json")])

    def test_canale(self):
        v = Session.for_service(self.cfg.services["canale5"], now=0)
        self.assertEqual((v.what, v.sid, v.title), ("channel", "canale5", "Canale 5"))
        self.assertTrue(v.live and v.curtain and v.banner and v.guarded and v.reopen and v.remember)
        self.assertTrue(v.kick and v.auto_fullscreen)                    # diretta web
        self.assertEqual(v.watch.cid, "canale5")

    def test_canale_rai(self):
        v = Session.for_service(self.cfg.services["rai1"], now=0)
        self.assertTrue(v.curtain and v.reopen)
        self.assertFalse(v.kick or v.auto_fullscreen)                     # app HbbTV: fa tutto lei

    def test_episodio(self):
        v = Session.episode("https://mediasetinfinity.mediaset.it/video/x/y_F1", "SERIE", "Don Matteo · Ep. 3", now=0)
        self.assertEqual(v.what, "episode")
        self.assertIsNone(v.sid)
        self.assertEqual(v.return_to, "ms:SERIE")
        self.assertEqual(v.title, "Don Matteo · Ep. 3")
        self.assertTrue(v.curtain and v.guarded and v.kick and v.auto_fullscreen)
        self.assertFalse(v.live or v.banner or v.reopen or v.remember)
        self.assertEqual(v.service["block"], ["trackers"])

    def test_servizio_e_sito(self):
        v = Session.for_service(self.cfg.services["youtube"], now=0)
        self.assertEqual(v.what, "service")
        self.assertFalse(v.curtain or v.guarded or v.remember or v.watch)
        s = Session.site("https://www.prova.it/a", mobile=True, now=0)
        self.assertEqual(s.what, "site")
        self.assertTrue(s.service["mobile"] and s.service["shield"] and s.auto_fullscreen)
        self.assertEqual(s.service["block"], ["ads"])
        self.assertFalse(s.curtain or s.guarded)

    def test_pagine_della_visione(self):
        v = Session.for_service(self.cfg.services["canale5"], now=0)
        self.assertTrue(v.owns("https://mediasetinfinity.mediaset.it/diretta/canale5_cC5"))
        self.assertTrue(v.owns("https://mediasetinfinity.mediaset.it/altro"))   # stesso sito
        self.assertFalse(v.owns("https://www.raiplay.it/"))
        self.assertFalse(v.owns(""))

    def test_nessun_servizio_finto(self):
        """Episodi e siti non aggiungono servizi all'elenco (in V3: __episodio, __sito)."""
        n = len(self.cfg.services)
        Session.episode("https://mediasetinfinity.mediaset.it/video/x/y_F1", "S", now=0)
        Session.site("https://www.prova.it/", now=0)
        self.assertEqual(len(self.cfg.services), n)


if __name__ == "__main__":
    unittest.main()

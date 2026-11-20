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
from tvbox.util import read_json  # noqa: E402
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

    def test_menu_lungo_nel_launcher(self):
        self.assertEqual(keys.action_for(keys.LAUNCHER, "menu_long"), "launcher_long")
        self.assertEqual(keys.action_for(keys.SITE, "menu_long"), "home")

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


class DiscoveryTest(unittest.TestCase):
    @staticmethod
    def jwt(claims):
        import base64
        b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
        return f"{b({'alg': 'RS256'})}.{b(claims)}.firma"

    def test_collegati_dal_gettone_st(self):
        from tvbox.discovery import is_logged, token_claims
        now = 1_800_000_000
        anon = [{"name": "st", "value": self.jwt({"anonymous": True, "exp": now + 99})}]
        user = [{"name": "x", "value": "y"}, {"name": "st", "value": self.jwt({"anonymous": False, "exp": now + 99})}]
        old = [{"name": "st", "value": self.jwt({"anonymous": False, "exp": now - 1})}]
        self.assertFalse(is_logged(token_claims(anon), now))
        self.assertTrue(is_logged(token_claims(user), now))
        self.assertFalse(is_logged(token_claims(old), now))          # scaduto
        self.assertIsNone(token_claims([{"name": "st", "value": "rotto"}]))
        self.assertIsNone(token_claims([]))

    def test_modulo_senza_iniezioni(self):
        from tvbox.discovery import fill_js
        js = fill_js('a@b.it', 'pa"ss\'); </script>')
        self.assertIn(json.dumps('pa"ss\'); </script>'), js)          # stringa JSON, non codice


class ProgressTest(unittest.TestCase):
    def test_da_dove_riprendere(self):
        from tvbox.health import resume_point
        self.assertIsNone(resume_point(None))
        self.assertIsNone(resume_point([30, 1500, 0]))          # primo minuto: dall'inizio
        self.assertEqual(resume_point([600, 1500, 0]), 600)
        self.assertIsNone(resume_point([1450, 1500, 0]))        # ultimi 2 minuti: dall'inizio

    def test_prefs_solo_valori_validi_e_al_massimo_200(self):
        from tvbox.prefs import PROGRESS_MAX
        pr = {f"https://x/{i}": [10, 100, i] for i in range(PROGRESS_MAX + 20)}
        pr.update({"rotto": [1, 2], "zero": [1, 0, 5], "testo": ["a", 1, 2]})
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "prefs.json"), "w") as f:
                json.dump({"version": 3, "progress": pr}, f)
            got = Prefs(d).get("progress")
        self.assertEqual(len(got), PROGRESS_MAX)
        self.assertNotIn("https://x/0", got)                      # i più vecchi escono
        self.assertIn(f"https://x/{PROGRESS_MAX + 19}", got)
        self.assertFalse({"rotto", "zero", "testo"} & got.keys())


class PrefsTest(unittest.TestCase):
    def test_servizi_in_home_solo_validi(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "prefs.json"), "w") as f:
                json.dump({"version": 3, "pinned": ["la7", 5, None, "rai1", "plutotv"]}, f)
            self.assertEqual(Prefs(d).get("pinned"), ["la7", "plutotv"])

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

    def test_dalla_versione_3(self):
        """"Il mio catalogo" diventa "sc": Continua a guardare, riquadri in home e nascosti restano."""
        h = [{"series": "123-serie", "episode": "https://x/it/watch/1", "title": "Serie"}]
        with tempfile.TemporaryDirectory() as d:
            wjson(os.path.join(d, "prefs.json"), {"version": 3, "mio_history": h,
                                                 "pinned": ["mio", "la7"], "hidden": ["mio"]})
            p = Prefs(d)
            self.assertEqual(p.get("sc_history"), h)
            self.assertEqual(p.get("pinned"), ["sc", "la7"])
            self.assertEqual(p.get("hidden"), ["sc"])
            self.assertEqual(Prefs(d).get("sc_history"), h)                  # salvato
            self.assertNotIn("mio_history", read_json(os.path.join(d, "prefs.json")))

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


class LoginTest(unittest.TestCase):
    """Accesso fatto da tvd: Mediaset (Gigya) e StreamingCommunity (modulo del sito)."""
    class FakeCDP:
        def __init__(self, names):
            self.cookies = [{"name": n, "value": "x", "domain": ".mediaset.it", "path": "/"} for n in names]

        def call(self, method, params=None, timeout=6):
            return {"cookies": self.cookies}

    def test_mediaset_collegato_solo_con_cookie_di_sessione(self):
        from tvbox.mediaset import Mediaset
        with tempfile.TemporaryDirectory() as d:
            p = Prefs(d)
            p.set("ms_user", "io@example.com")
            self.assertFalse(Mediaset(p, self.FakeCDP(["gmid", "ucid"])).login_state()["logged"])
            st = Mediaset(p, self.FakeCDP(["gmid", "glt_3_abc"])).login_state()
            self.assertTrue(st["logged"])
            self.assertEqual(st["user"], "io@example.com")
            self.assertEqual(Prefs(d).get("ms_user"), "io@example.com")     # resta nel file

    def test_mediaset_messaggi(self):
        from tvbox.mediaset import gigya_login_js, login_message
        self.assertEqual(login_message(403042), "Email o password non corretti")
        js = gigya_login_js('a"b@x.it', "p'w\\")
        self.assertIn('"loginID": "a\\"b@x.it"', js)                      # niente stringhe montate a mano
        self.assertIn("gigya.accounts.login", js)

    def test_mediaset_campi_vuoti(self):
        from tvbox.mediaset import Mediaset
        self.assertFalse(Mediaset(None, self.FakeCDP([])).login(" ", "")["ok"])

    def test_sc_pagina_del_sito(self):
        from tvbox.sc import is_session_cookie, login_error, page_props, page_user
        props = page_props('<div data-page="{&quot;props&quot;:{&quot;errors&quot;:{&quot;username&quot;:'
                           '&quot;Credenziali non valide.&quot;},&quot;auth&quot;:{&quot;user&quot;:null}}}">')
        self.assertIsNone(page_user(props))
        self.assertEqual(login_error(props), "Credenziali non valide.")
        self.assertEqual(page_user(page_props('{"props": {"auth": {"user": {"username": "io"}}}}')), {"username": "io"})
        self.assertTrue(is_session_cookie("remember_web_59ba36"))
        self.assertFalse(is_session_cookie("XSRF-TOKEN"))


class AnimeUnityTest(unittest.TestCase):
    """tvbox/au.py: la parte già pronta (classe AU), con un connettore finto al posto di quello
    vero: i test non vanno mai sul sito e valgono qualunque cosa ci sia nel connettore."""
    PARTS = ("SITE_HOST", "BASE_URL", "EPISODE_PATH", "SESSION_COOKIES", "LOGIN_REQUIRED",
             "fetch_home", "fetch_anime", "fetch_search", "fetch_series", "site_login", "site_user",
             "resolve_episode", "fetch_details", "_adult_ids")

    def setUp(self):
        import tvbox.au as au
        self.au, self.d = au, tempfile.TemporaryDirectory()
        self.saved = {k: getattr(au, k) for k in self.PARTS}

        def todo(*a, **k):
            raise NotImplementedError("finto")
        for k in ("fetch_home", "fetch_anime", "fetch_search", "fetch_series", "site_login", "site_user",
                  "resolve_episode", "fetch_details"):
            setattr(au, k, todo)                                           # di partenza: connettore vuoto
        au.SITE_HOST, au.BASE_URL, au.EPISODE_PATH = "anime.example", "https://anime.example", "/anime/"
        au.SESSION_COOKIES, au.LOGIN_REQUIRED = (), True
        au._adult_ids = lambda: frozenset()                                # niente rete nei test

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(self.au, k, v)
        self.d.cleanup()

    def test_connettore_vuoto(self):
        a = self.au.AU(Prefs(self.d.name))
        r = a.rails("home")
        self.assertEqual(r["rails"], [])
        self.assertIn("non ancora scritto", r["error"])
        self.assertIn("non ancora scritto", a.series("x")["error"])
        self.assertIn("non ancora scritto", a.search("naruto")["error"])
        self.assertFalse(a.login_state()["logged"])

    def test_connettore_finto(self):
        au = self.au
        au.fetch_home = lambda: [{"id": "top", "title": "Popolari", "items": [au.serie("1-op", "One Piece", "p.jpg")]}]
        au.fetch_series = lambda sid, season=None: (au.serie(sid, "One Piece"), [
            au.episodio("e2", "https://anime.example/anime/1-op/2", n=2),
            au.episodio("x", "https://altro.example/anime/1", n=1)])          # fuori dal sito: scartato
        a = au.AU(Prefs(self.d.name))
        a.remember({"series": "1-op", "title": "One Piece", "poster": "p.jpg", "episode": "e2", "n": "2"})
        r = a.rails("home")
        self.assertEqual([x["id"] for x in r["rails"]], ["continua", "top"])
        s = a.series("1-op")
        self.assertEqual([e["id"] for e in s["episodes"]], ["e2"])
        self.assertEqual(s["last"], "e2")
        self.assertEqual(s["seasons"][0]["title"], "Episodi")

    def test_descrizione_di_un_titolo_evidenziato(self):
        au, calls = self.au, []
        a = au.AU(Prefs(self.d.name))
        self.assertEqual(a.details("1-op"), {})                            # connettore senza: niente
        au.fetch_details = lambda sid: calls.append(sid) or au.serie(sid, "One Piece", desc="Pirati", genres=["Action"])
        self.assertEqual(a.details("1-op")["desc"], "Pirati")
        a.details("1-op")
        self.assertEqual(calls, ["1-op"])                                  # la seconda volta dalla cache

    def test_serie_lunghissima_a_gruppi(self):
        au = self.au
        eps = [au.episodio(f"e{n}", f"https://anime.example/anime/1-op/{n}", n=n) for n in range(250, 0, -1)]
        au.fetch_series = lambda sid, season=None: (au.serie(sid, "One Piece"), list(eps))
        p = Prefs(self.d.name)
        a = au.AU(p)
        r = a.series("1-op")
        self.assertEqual([x["id"] for x in r["seasons"]], ["1-100", "101-200", "201-250"])
        self.assertEqual((r["season"], len(r["episodes"])), ("1-100", 100))    # mai vista: dal primo gruppo
        self.assertEqual([e["n"] for e in r["episodes"][:3]], [1, 2, 3])    # dal primo episodio
        self.assertTrue(r["ascending"])
        self.assertEqual(len(a.series("1-op", "101-200")["episodes"]), 100)
        a.remember({"series": "1-op", "title": "One Piece", "episode": "e142", "n": "142"})
        self.assertEqual(a.series("1-op")["season"], "101-200")             # dove si era arrivati
        a.remember({"series": "1-op", "title": "One Piece", "episode": "e242", "n": "242", "season": "201-250"})
        self.assertEqual(a.series("1-op")["season"], "201-250")             # la stagione salvata
        short = [au.episodio(f"e{n}", f"https://anime.example/anime/2-x/{n}", n=n) for n in range(12, 0, -1)]
        au.fetch_series = lambda sid, season=None: (au.serie(sid, "Corta"), list(short))
        self.assertEqual(len(a.series("2-x")["seasons"]), 1)                # serie normali: come prima

    def test_titoli_per_adulti_a_scelta(self):
        au = self.au
        au._adult_ids = lambda: frozenset({2})                           # elenco del sito (finto)
        items = [au.serie("1-a", "A"), au.serie("2-b", "B"), dict(au.serie("3-c", "C"), adult=True)]
        au.fetch_home = lambda: [{"id": "r", "title": "Riga", "items": items}]
        p = Prefs(self.d.name)
        a = au.AU(p)
        self.assertEqual([x["id"] for x in a.rails("home")["rails"][0]["items"]], ["1-a"])   # di serie nascosti
        p.set("au_adult", True)
        self.assertEqual([x["id"] for x in a.rails("home")["rails"][0]["items"]], ["1-a", "2-b", "3-c"])

    def test_player_da_solo_o_pagina_episodio(self):
        au, ep = self.au, "https://anime.example/anime/1-op/2"
        a = au.AU(Prefs(self.d.name))
        self.assertEqual(a.play_target(ep), (ep, None))                    # connettore senza player: la pagina
        au.resolve_episode = lambda u: ("https://player.example/embed/9", "https://anime.example/")
        self.assertEqual(a.play_target(ep), ("https://player.example/embed/9", "https://anime.example/"))

        def rotto(u):
            raise ValueError("pagina cambiata")
        au.resolve_episode = rotto
        self.assertEqual(a.play_target(ep), (ep, None))                    # player non trovato: la pagina

    def test_accesso_copia_i_cookie_in_chrome(self):
        au = self.au
        au.SESSION_COOKIES = ("au_session",)

        class FakeCDP:
            def __init__(self): self.cookies = []
            def call(self, method, params=None, timeout=6):
                if method == "Network.setCookie":
                    self.cookies.append(dict(params, domain="anime.example"))
                if method == "Network.deleteCookies":
                    self.cookies = [c for c in self.cookies if c["name"] != params["name"]]
                return {"cookies": self.cookies}

        def site_login(opener, jar, user, pw):
            import http.cookiejar
            jar.set_cookie(http.cookiejar.Cookie(0, "au_session", "x", None, False, "anime.example", False, False,
                                                 "/", True, True, None, False, None, None, {}))
            return {"ok": pw == "giusta", "user": user, "error": "Credenziali non valide"}
        au.site_login = site_login
        cdp = FakeCDP()
        a = au.AU(Prefs(self.d.name), cdp)
        self.assertEqual(a.login("io", "sbagliata")["error"], "Credenziali non valide")
        self.assertEqual(cdp.cookies, [])                                  # niente cookie se l'accesso fallisce
        self.assertTrue(a.login("io", "giusta")["ok"])
        self.assertEqual([c["name"] for c in cdp.cookies], ["au_session"])
        self.assertTrue(a.login_state(fresh=True)["logged"])
        self.assertFalse(a.logout()["logged"])
        self.assertEqual(cdp.cookies, [])


class StreamingCommunityPlayerTest(unittest.TestCase):
    """sc.py: dal riquadro della pagina dell'episodio al player da aprire da solo."""
    def test_riquadro_episodio_e_film(self):
        from tvbox.sc import iframe_url
        self.assertEqual(iframe_url("https://streamingunity.day/it/watch/3242?e=77527"),
                         "https://streamingunity.day/it/iframe/3242?episode_id=77527")
        self.assertEqual(iframe_url("https://streamingunity.day/it/watch/66468"),
                         "https://streamingunity.day/it/iframe/66468")
        with self.assertRaises(ValueError):
            iframe_url("https://streamingunity.day/it/titles/66468")

    def test_ripiego_sulla_pagina(self):
        import tvbox.sc as sc
        saved = sc.resolve_episode

        def rotto(u):
            raise ValueError("sito cambiato")
        try:
            sc.resolve_episode = rotto
            ep = "https://streamingunity.day/it/watch/3242?e=77527"
            self.assertEqual(sc.SC(None).play_target(ep), (ep, None))
        finally:
            sc.resolve_episode = saved


class EpisodeKeyTest(unittest.TestCase):
    def test_player_da_solo(self):
        """AnimeUnity: si apre il player con la provenienza, il punto si salva sull'episodio."""
        v = Session.episode("https://player.example/embed/9?token=x", "1-op", "Ep. 2", site="AnimeUnity",
                            back="au", referrer="https://anime.example/", key="https://anime.example/anime/1-op/2")
        self.assertEqual(v.url, "https://player.example/embed/9?token=x")
        self.assertEqual(v.key, "https://anime.example/anime/1-op/2")
        self.assertEqual(v.referrer, "https://anime.example/")
        self.assertEqual(v.return_to, "au:1-op")
        w = Session.episode("https://mediasetinfinity.mediaset.it/video/x/ep_F1", "s1")   # come prima
        self.assertEqual((w.key, w.referrer), (w.url, None))


class EpisodesTest(unittest.TestCase):
    """episodes.py: episodio successivo (scelta, stagione dopo, riquadro e partenza automatica)."""
    def ep(self, n, date=0):
        return {"id": f"e{n}", "url": f"https://x/{n}", "title": f"Ep {n}", "n": n, "date": date}

    def test_successivo_nella_lista(self):
        from tvbox.episodes import next_episode
        eps = [self.ep(3), self.ep(2), self.ep(1)]                          # dal più recente, come i cataloghi
        self.assertEqual(next_episode(eps, "e1")["id"], "e2")
        self.assertIsNone(next_episode(eps, "e3"))                          # l'ultimo
        self.assertIsNone(next_episode(eps, "e9"))                          # non c'è
        by_date = [dict(self.ep(None, 300), id="c"), dict(self.ep(None, 100), id="a"), dict(self.ep(None, 200), id="b")]
        self.assertEqual(next_episode(by_date, "a")["id"], "b")             # puntate senza numero: per data

    def fake_tv(self, seasons):
        from tvbox.episodes import EpisodesMixin

        class Cat:
            def series(self, sid, season=None):
                k = season or list(seasons)[-1]
                return {"season": k, "seasons": [{"id": x} for x in seasons], "episodes": list(reversed(seasons[k]))}

        class T(EpisodesMixin):
            sc = Cat()
        return T()

    def test_successivo_nella_stagione_dopo(self):
        t = self.fake_tv({"1": [self.ep(1), self.ep(2)], "2": [self.ep(1), self.ep(2)]})
        info = {"cat": "sc", "series": "s", "season": "1", "episode": "e2", "title": "Serie", "poster": "p"}
        n = t.find_next(info)
        self.assertEqual((n["season"], n["episode"], n["ep"]), ("2", "e1", "Ep 1"))
        self.assertEqual(n["title"], "Serie")                               # i dati della serie restano
        self.assertIsNone(t.find_next(dict(info, season="2")))              # ultimo dell'ultima stagione

    def test_riquadro_e_partenza(self):
        from tvbox.episodes import NEXT_LOOKUP, NEXT_SHOW
        t = self.fake_tv({"1": [self.ep(1), self.ep(2)]})
        shown, posted = [], []
        t.layer = lambda m, *a, **k: shown.append((m, a))
        t.post = lambda fn, *a: posted.append(fn)
        sess = Session.episode("https://x/1", "s", "Ep 1", back="sc")
        sess.info = {"cat": "sc", "series": "s", "season": "1", "episode": "e1"}
        t.session = sess
        t._episode_tick(sess, {"t": 100, "d": 1000}, 0)
        self.assertIsNone(sess.next_info)                                   # lontani dalla fine: niente
        t._lookup_next = lambda s: setattr(s, "next_info", t.find_next(s.info))
        import tvbox.episodes as E
        saved = E.threading.Thread
        E.threading.Thread = lambda target, args, daemon: type("X", (), {"start": lambda self: target(*args)})()
        try:
            t._episode_tick(sess, {"t": 1000 - NEXT_LOOKUP + 1, "d": 1000}, 1)
        finally:
            E.threading.Thread = saved
        self.assertEqual(sess.next_info["episode"], "e2")                   # cercato, ma non ancora mostrato
        self.assertEqual(shown, [])
        t._episode_tick(sess, {"t": 1000 - NEXT_SHOW, "d": 1000}, 10)        # a 10 s: riquadro con il conto
        self.assertEqual(shown[-1][1][0]["wait"], NEXT_SHOW)
        t._episode_tick(sess, {"t": 1000 - NEXT_SHOW + 2, "d": 1000, "paused": True}, 12)   # pausa: via
        self.assertEqual(shown[-1], ("next", (None,)))
        self.assertIsNone(sess.next_at)
        t._episode_tick(sess, {"t": 1000 - 6, "d": 1000}, 20)               # riparte: conto dai 6 s che mancano
        self.assertEqual(shown[-1][1][0]["wait"], 6)
        t._episode_tick(sess, {"t": 1000, "d": 1000, "ended": True}, 26)    # finito il conto: parte
        t._episode_tick(sess, {"t": 1000, "d": 1000, "ended": True}, 28)
        self.assertEqual(len(posted), 1)                                    # parte una volta sola


class ChromeUpdateTest(unittest.TestCase):
    """Chrome aggiornato di notte: si riavvia solo a schermo spento."""
    def test_solo_a_schermo_spento(self):
        from tvbox.tv import TV
        killed = []

        class B:
            def updated_since_start(self): return True
            def kill(self): killed.append(1)

        class C:
            def drop(self): pass
        t = type("T", (), {"browser": B(), "cdp": C(), "asleep": False})()
        TV._chrome_update_tick(t)
        self.assertEqual(killed, [])                                       # schermo acceso: mai
        t.asleep = True
        TV._chrome_update_tick(t)
        TV._chrome_update_tick(t)                                           # al più ogni 10 minuti
        self.assertEqual(killed, [1])


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

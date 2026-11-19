"""Server per le prove della grafica: il launcher del progetto e le vere API di tvd
(tvbox.api.make_routes) con una TV finta. Configurazione, canali, palinsesti, guida e Mediaset
sono veri (servono internet); meteo, rete e schermo sono di fantasia.

    python3 tools/uitest/server.py [porta]
"""
import http.server, json, sys, tempfile
from urllib.parse import urlparse, parse_qs
import os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import tvbox.sites as sites
sites.ICON_DIR = tempfile.mkdtemp()
from tvbox.api import make_routes, Binary
from tvbox.config import Config
from tvbox.epg import EPG
from tvbox.mediaset import Mediaset
from tvbox.sc import SC
from tvbox.prefs import Prefs
from tvbox.sites import Sites

class FakeCDP:
    """Chrome finto: solo i cookie. Mediaset risulta collegato (cookie di Gigya), salvo
    UITEST_LOGGED_OUT=1 per vedere la schermata di accesso."""
    def call(self, method, params=None, timeout=6):
        if method == "Network.getCookies" and not os.environ.get("UITEST_LOGGED_OUT"):
            return {"cookies": [{"name": "glt_prova", "value": "x", "domain": ".mediaset.it", "path": "/"}]}
        return {"cookies": []}

class FakeTV:
    def __init__(self):
        self.cfg = Config.load([ROOT + "/config.json"]); self.prefs = Prefs(tempfile.mkdtemp())
        self.services = self.cfg.services; self.sites = Sites(self.prefs); self.mediaset = Mediaset(self.prefs, FakeCDP()); self.sc = SC(self.prefs)
        self.epg = EPG(self.services, enabled=self.channel_list); self.remote = None
    def channel_list(self): return self.cfg.live_channels(self.prefs.get("channels"))
    def post(self, *a): pass
    def open(self, *a, **k):
        return None
    def sleep_left(self): return 0
    def sleep_set(self, m): return {"minutes": m}
    def volume(self, d=0): return 60
TV = FakeTV(); ROUTES = make_routes(TV)
STUB = {"meteo": {"city": "Roma", "temp": 18, "text": "Sereno", "icon": "🌙"},
        "wifi": {"present": True, "connected": True, "ssid": "Wi-Fi di casa", "ip": "192.168.1.50"},
        "info": {"ip": ["192.168.1.50"]},
        "screen": {"current": "1280x720", "video_mode": "1280x720", "video_low": True, "modes": ["1280x720"], "saved": "1280x720", "preferred": "1280x720"}}
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(s, *a, **k): super().__init__(*a, directory=ROOT + "/launcher", **k)
    def log_message(s, *a): pass
    def end_headers(s):        # come tvd: Chrome ricontrolla sempre i file (niente copie vecchie)
        s.send_header("Cache-Control", "no-cache"); super().end_headers()
    def do_GET(s):
        u = urlparse(s.path)
        if u.path.startswith("/__test/"):            # pagine finte per tvtest.py (pages/)
            name = os.path.basename(u.path)
            try: body = open(os.path.join(ROOT, "tools/uitest/pages", name), "rb").read()
            except OSError: return s.send_error(404)
            s.send_response(200); s.send_header("Content-Type", "text/html; charset=utf-8"); s.send_header("Content-Length", str(len(body))); s.end_headers(); return s.wfile.write(body)
        if not u.path.startswith("/api/"): return super().do_GET()
        ep, q = u.path[5:], {k: v[0] for k, v in parse_qs(u.query).items()}
        if ep not in STUB and ep not in ROUTES:     # come tvd: indirizzo sconosciuto = 404, non un errore
            return s.send_error(404)               # (es. una pagina vecchia che chiede ancora /api/mio)
        res = STUB[ep] if ep in STUB else ROUTES[ep](q)
        if isinstance(res, tuple): res = res[0]
        if isinstance(res, Binary): body, ct = res.data, res.ctype
        else: body, ct = json.dumps(res).encode(), "application/json"
        s.send_response(200); s.send_header("Content-Type", ct); s.send_header("Content-Length", str(len(body))); s.end_headers(); s.wfile.write(body)
http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8799), H).serve_forever()

"""Catalogo dei canali in diretta (Rai, Mediaset, Discovery) e canali scelti dall'utente.

Ogni canale diventa un servizio come quelli di config.json (vedi config.normalize_service).
L'utente sceglie in Impostazioni quali canali vanno nella home e in che ordine: la scelta è
nelle preferenze ("channels"); di serie i nove canali della V2.

Fonti degli indirizzi (verificati):
    Rai        app RaiPlay per TV + /dirette/<canale>.json  (elenco: raiplay.it/dirette.json)
    Mediaset   mediasetinfinity.mediaset.it/diretta/<nome>_c<sigla>  (sigle: feed "stations")
    Discovery  discoveryplus.com/channel/watch/<canale>/<video>  (pagina pubblica di discovery+)
"""
from .config import normalize_service

RAI_APP = ("https://www.raiplay.it/hbbtv/wsA6DXk6W7Khjpn3/RaiPlay2020/index.html"
           "?type=RaiPlay%20Diretta%20Item&path_id=%2Fdirette%2F{slug}.json")
MEDIASET = "https://mediasetinfinity.mediaset.it/diretta/{slug}_c{code}"
DPLUS = "https://www.discoveryplus.com/channel/watch/{cid}/{vid}"

# (id, nome, nome nel palinsesto Rai)
RAI = [("rai1", "Rai 1"), ("rai2", "Rai 2"), ("rai3", "Rai 3"), ("rai4", "Rai 4"), ("rai5", "Rai 5"),
       ("raimovie", "Rai Movie"), ("raipremium", "Rai Premium"), ("raistoria", "Rai Storia"),
       ("rainews24", "Rai News 24"), ("raisport", "Rai Sport"), ("italiana", "Italiana"),
       ("raiyoyo", "Rai Yoyo"), ("raigulp", "Rai Gulp"), ("rai4k", "Rai 4K")]
# (id, nome, sigla Mediaset, nome nell'indirizzo)
MEDIASET_CH = [("canale5", "Canale 5", "C5", "canale5"), ("italia1", "Italia 1", "I1", "italia1"),
               ("rete4", "Rete 4", "R4", "rete4"), ("venti", "20", "LB", "20"), ("la5", "La 5", "KA", "la5"),
               ("iris", "Iris", "KI", "iris"), ("topcrime", "Top Crime", "LT", "topcrime"),
               ("focus", "Focus", "FU", "focus"), ("italia2", "Italia 2", "I2", "italia2"),
               ("tgcom24", "TGCom24", "KF", "tgcom24"), ("mediasetextra", "Mediaset Extra", "KQ", "mediasetextra"),
               ("cine34", "Cine34", "B6", "cine34"), ("twentyseven", "Twentyseven", "TS", "twentyseven"),
               ("boing", "Boing", "KB", "boing"), ("cartoonito", "Cartoonito", "LA", "cartoonito")]
# (id, nome, canale discovery+, video discovery+, guida TV Discovery o None, colore)
DISCOVERY = [
    ("realtime", "Real Time", "1b4dfb81-d38a-5508-a4f3-ab9938aa0c8c", "2c96b2f2-ff68-5662-964d-825a8506e626", "realtime", "#9d174d"),
    ("dmax", "DMAX", "da3cc7e5-a1e9-5c03-ac00-edc598104362", "012782b6-b7c5-5db4-ae2a-23465bdab0d4", "dmaxit", "#9a3412"),
    ("nove", "Nove", "daf976fa-2a48-5fcb-99ac-7c6e3dc340d5", "772eea69-b375-5448-8fcc-4bcd29b7e2a0", "nove", "#1e40af"),
    ("foodnetwork", "Food Network", "7b71339e-95ba-5c6c-ad91-92a69a40af8e", "08b84b1e-e21a-59e9-931d-d67aca3e2e37", "foodnetwork", "#b45309"),
    ("hgtv", "HGTV", "70184000-e094-50ac-8c81-a3a6e5cf25d0", "0dd0b519-ef25-593e-bf4f-009803389e5a", "hgtvit", "#15803d"),
    ("giallo", "Giallo", "16005ef7-f449-5abe-8aca-b2a654d6d6ca", "020d59b3-0136-5ab3-85c2-635410933dd0", None, "#a16207"),
    ("k2", "K2", "f4a4e9af-8af5-54a1-96b8-281b59b00742", "366a7d01-78f8-568b-a429-54dcc5f6a1d6", None, "#0e7490"),
    ("frisbee", "Frisbee", "0056c9f0-e41e-5adc-80c0-dba41beaa77b", "95e29bf3-0593-5589-bf63-133456ed024c", None, "#7c3aed"),
    ("discoverychannel", "Discovery Channel", "d90405c0-43b6-51f3-97cb-cb9271b4ef62", "a6169d4c-51f2-569e-86a7-96bad1b74c5d", None, "#1d4ed8"),
    ("discoveryturbo", "Discovery Turbo", "cf0ac36b-c39a-5ae8-8e95-2c651e7c4bf9", "8d896b58-5b3b-5685-8a38-887f17f00764", None, "#b91c1c"),
]
DEFAULT = ["rai1", "rai2", "rai3", "rete4", "canale5", "italia1", "realtime", "dmax", "nove"]
GROUPS = [("rai", "Rai"), ("mediaset", "Mediaset"), ("discovery", "Discovery")]


def catalog(identities):
    """{id: servizio} per tutti i canali, ognuno con "group" (rai / mediaset / discovery)."""
    raw = {}
    for cid, name in RAI:
        raw[cid] = {"kind": "hbbtv", "identity": "samsung_tv", "live": True, "onair": "rai:" + name,
                    "label": name, "icon": "tv", "color": "#1e3a8a", "group": "rai",
                    "url": RAI_APP.format(slug=cid)}
    for cid, name, code, slug in MEDIASET_CH:
        raw[cid] = {"kind": "web", "live": True, "onair": "ms:" + code, "block": ["trackers"],
                    "label": name, "icon": "tv", "color": "#115e59", "group": "mediaset",
                    "url": MEDIASET.format(slug=slug, code=code)}
    for cid, name, ch, vid, guide, color in DISCOVERY:
        raw[cid] = {"kind": "web", "live": True, "label": name, "icon": "tv", "color": color,
                    "group": "discovery", "url": DPLUS.format(cid=ch, vid=vid)}
        if guide:
            raw[cid]["onair"] = "wbd:" + guide
    return {cid: normalize_service(cid, s, identities) for cid, s in raw.items()}


def clean_selection(ids, known):
    """La scelta dell'utente, senza doppioni né canali che non esistono più."""
    out = []
    for i in ids if isinstance(ids, list) else []:
        if isinstance(i, str) and i in known and i not in out:
            out.append(i)
    return out

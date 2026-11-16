"""Stati della TV e tabella "tasto -> azione".

In ogni momento la TV è in uno stato (detect_mode). Per ogni stato la tabella KEYMAP dice
quale azione fa ciascun tasto. Aggiungere una funzione = aggiungere uno stato o una riga,
senza toccare le altre (in V1 erano catene di "se" sparse in back/ok/arrow).

Tasti logici: up down left right · ok ok_long · menu menu_long · play · home
"""
from dataclasses import dataclass

LAUNCHER = "launcher"        # la home e le sue pagine (gestite dal launcher stesso)
PANEL = "panel"              # pannello cambio canale sopra una diretta
POINTER = "pointer"          # puntatore: le frecce muovono il mouse
LIVE_TV = "live_tv"          # diretta dentro l'app per TV (Rai, HbbTV)
LIVE_PLAYER = "live_player"  # diretta web con il video a tutto schermo (Mediaset, WBD)
LIVE_SITE = "live_site"      # diretta web mentre la pagina si carica (banner, pulsanti)
TVAPP_HBBTV = "hbbtv"        # app per TV HbbTV (RaiPlay)
TVAPP = "tvapp"              # app per TV leanback (YouTube TV)
PLAYER = "player"            # video a tutto schermo in un sito
SITE = "site"                # sito con navigazione assistita (riquadro giallo)
WEB = "web"                  # sito senza navigazione assistita


@dataclass
class Context:
    on_launcher: bool = False
    panel: bool = False
    pointer: bool = False
    kind: str = "web"            # tipo del servizio aperto (config.KIND_DEFAULTS)
    live: bool = False           # è un canale in diretta con palinsesto
    player: bool = False         # c'è un video grande in riproduzione e il servizio usa i tasti player
    assist: bool = True          # navigazione assistita ammessa


def detect_mode(c):
    if c.panel:
        return PANEL
    if c.pointer:
        return POINTER
    if c.on_launcher:
        return LAUNCHER
    if c.live:
        if c.kind == "hbbtv":
            return LIVE_TV
        return LIVE_PLAYER if c.player else LIVE_SITE
    if c.kind == "hbbtv":
        return TVAPP_HBBTV
    if c.kind == "tvapp":
        return TVAPP
    if c.player:
        return PLAYER
    return SITE if c.assist else WEB


ARROWS4 = ("up", "down", "left", "right")


def _arrows(action):
    return {d: action for d in ARROWS4}


# valgono in ogni stato, salvo diversa indicazione dello stato
COMMON = {"home": "home", "menu_long": "home", "ok_long": "pointer_toggle"}

KEYMAP = {
    LAUNCHER:    {**_arrows("key_arrow"), "ok": "key_enter", "play": "key_enter", "menu": "key_esc"},
    PANEL:       {"left": "panel_move", "right": "panel_move", "up": "panel_volume", "down": "panel_volume",
                  "ok": "panel_ok", "menu": "panel_close", "play": "panel_close", "ok_long": None},
    POINTER:     {**_arrows("pointer_nudge"), "ok": "click", "menu": "pointer_off", "play": "player_toggle"},
    # sulle dirette: + − volume, ◄ ► pannello già spostato sul canale vicino
    LIVE_TV:     {"up": "player_volume", "down": "player_volume", "left": "panel_step", "right": "panel_step",
                  "ok": "key_enter", "menu": "panel_open", "play": "tv_play"},
    LIVE_PLAYER: {"up": "player_volume", "down": "player_volume", "left": "panel_step", "right": "panel_step",
                  "ok": "player_toggle", "menu": "panel_open", "play": "player_toggle"},
    LIVE_SITE:   {**_arrows("nav_move"), "ok": "nav_ok", "menu": "panel_open", "play": "player_toggle"},
    TVAPP_HBBTV: {**_arrows("key_arrow"), "ok": "key_enter", "menu": "tv_back", "play": "tv_play"},
    TVAPP:       {**_arrows("key_arrow"), "ok": "key_enter", "menu": "key_esc", "play": "player_toggle"},
    # OK nel video: "Salta intro" / "Episodio successivo" se ci sono, altrimenti pausa
    PLAYER:      {"up": "player_volume", "down": "player_volume", "left": "player_seek", "right": "player_seek",
                  "ok": "player_ok", "menu": "page_back", "play": "player_toggle"},
    SITE:        {**_arrows("nav_move"), "ok": "nav_ok", "menu": "page_back", "play": "player_toggle"},
    WEB:         {**_arrows("key_arrow"), "ok": "key_enter", "menu": "page_back", "play": "player_toggle"},
}


def action_for(mode, key):
    """Nome dell'azione (metodo di TV) per un tasto in uno stato; None = niente."""
    table = KEYMAP[mode]
    if key in table:
        return table[key]
    return COMMON.get(key)

"""Episodi dei cataloghi (Mediaset, StreamingCommunity, AnimeUnity): apertura, barra di
avanzamento ed episodio successivo.

La classe TV lo eredita da EpisodesMixin.

  play_episode(cat, q)   apre un episodio scelto nel launcher (/api/<cat>?action=play) o il
                         successivo; q = i dati dell'episodio (url, series, season, episode,
                         title, ep, n, poster…), gli stessi che il catalogo salva in
                         "Continua a guardare".
  _episode_tick(…)       chiamata dalla sorveglianza ogni 2 s: negli ultimi NEXT_LEAD secondi
                         mostra il riquadro "Episodio successivo"; finito l'episodio, il
                         successivo parte da solo dopo NEXT_WAIT secondi (MENU per non farlo).
  play_next()            OK sul riquadro: il successivo subito.
  seekbar(…)             la barra di avanzamento (pausa, salti, inizio dell'episodio).

next_episode() è la scelta pura del successivo: si prova con i test.
"""
import threading
import time

from .util import log

NEXT_LEAD = 40          # secondi dalla fine in cui compare "Episodio successivo"
NEXT_WAIT = 10          # finito l'episodio, il successivo parte dopo questi secondi
SEEKBAR_START = 5       # all'inizio dell'episodio la barra resta a schermo questi secondi

# catalogo -> (attributo della TV, nome del sito per il sipario, sezione per MENU, colore)
CATALOGS = {
    "mediaset": ("mediaset", "Mediaset Infinity", "ms", "#0f766e"),
    "sc": ("sc", "StreamingCommunity", "sc", "#9d174d"),
    "au": ("au", "AnimeUnity", "au", "#1e3a8a"),
}


def _order(e):
    """Posizione di un episodio nella serie: il numero, o la data se non è numerato."""
    n = e.get("n")
    return (0, n) if isinstance(n, (int, float)) else (1, e.get("date") or 0)


def next_episode(eps, current_id):
    """L'episodio dopo current_id nella stessa lista (qualunque sia l'ordine della lista): quello
    con il numero (o la data) subito più grande. None se current_id è l'ultimo o non c'è."""
    cur = next((e for e in eps if str(e.get("id")) == str(current_id)), None)
    if cur is None:
        return None
    later = [e for e in eps if _order(e) > _order(cur) and e.get("url")]
    return min(later, key=_order) if later else None


def first_episode(eps):
    """Il primo episodio di una lista (numero o data più piccoli)."""
    eps = [e for e in eps if e.get("url")]
    return min(eps, key=_order) if eps else None


def season_key(s):
    """Come il catalogo chiama una stagione nelle sue richieste (Mediaset: guid; gli altri: id)."""
    return s.get("guid") or s.get("id")


class EpisodesMixin:
    SEEKBAR_START = SEEKBAR_START
    # ---------- apertura ----------
    def play_episode(self, cat, q, now=False):
        """Apre l'episodio q del catalogo cat. Il lavoro che va in rete (il player da solo di
        StreamingCommunity e AnimeUnity) si fa qui; l'apertura vera passa dalla coda, salvo
        now=True (siamo già nel filo della coda, es. il successivo)."""
        attr, site, back, color = CATALOGS[cat]
        cat_obj = getattr(self, attr)
        site = self.services.get(cat, {}).get("label", site)
        cat_obj.remember(q)
        label = " · ".join(x for x in (q.get("title"), q.get("ep")) if x)
        target, referrer = (cat_obj.play_target(q["url"]) if hasattr(cat_obj, "play_target")
                            else (q["url"], None))
        info = dict(q, cat=cat)

        def go():
            self.open_episode(target, q.get("series", ""), label, site=site, back=back, color=color,
                              referrer=referrer, key=q["url"], info=info)
        go() if now else self.post(go)
        return {"ok": True}

    # ---------- episodio successivo ----------
    def find_next(self, info):
        """L'episodio dopo info nel catalogo (stessa stagione, o il primo della stagione dopo):
        i dati da passare a play_episode, o None se è l'ultimo."""
        cat_obj = getattr(self, CATALOGS[info["cat"]][0])
        sid = info.get("series")
        r = cat_obj.series(sid, info.get("season") or None)
        if not r or r.get("error"):
            return None
        nxt, season = next_episode(r.get("episodes") or [], info.get("episode")), r.get("season")
        if nxt is None and any(str(e.get("id")) == str(info.get("episode")) for e in r.get("episodes") or []):
            seasons = r.get("seasons") or []
            keys_ = [str(season_key(s)) for s in seasons]
            k = keys_.index(str(season)) if str(season) in keys_ else -1
            if 0 <= k < len(seasons) - 1:                       # la stagione dopo
                r2 = cat_obj.series(sid, season_key(seasons[k + 1]))
                if r2 and not r2.get("error"):
                    nxt, season = first_episode(r2.get("episodes") or []), r2.get("season")
        if nxt is None:
            return None
        return dict(info, url=nxt["url"], episode=str(nxt.get("id") or ""), season=season or "",
                    ep=nxt.get("title") or "", n="" if nxt.get("n") is None else str(nxt["n"]),
                    image=nxt.get("image") or info.get("hero") or info.get("poster") or "")

    def _lookup_next(self, sess):
        try:
            sess.next_info = self.find_next(sess.info) or False
        except Exception as ex:
            log.warning("episodio successivo: %s", ex)
            sess.next_info = False
        if sess.next_info and self.session is sess:
            self._show_next(sess)

    def _show_next(self, sess, wait=None):
        n = sess.next_info
        self.layer("next", {"title": " · ".join(x for x in (n.get("title"), n.get("ep")) if x),
                            "image": n.get("image") or "", "wait": wait}, timeout=3)

    def _episode_tick(self, sess, st, now):
        """Dalla sorveglianza (ogni 2 s, episodio in riproduzione): riquadro dell'episodio
        successivo verso la fine, partenza automatica a episodio finito."""
        t, d = st.get("t"), st.get("d")
        if not sess.info or not isinstance(t, (int, float)) or not isinstance(d, (int, float)) or d <= 0:
            return
        left = d - t
        if sess.next_info is None and left <= NEXT_LEAD and t > 5:
            sess.next_info = "…"                                 # una ricerca sola
            threading.Thread(target=self._lookup_next, args=(sess,), daemon=True).start()
            return
        if not isinstance(sess.next_info, dict):
            return
        ended = st.get("ended") or left <= 1
        if ended and sess.next_at is None:
            sess.next_at = now + NEXT_WAIT
            self._show_next(sess, wait=NEXT_WAIT)
        elif sess.next_at is not None and now >= sess.next_at:
            sess.next_at = float("inf")                          # una partenza sola
            self.post(self._autoplay_next, sess)

    def _autoplay_next(self, sess):
        if self.session is sess:
            self.play_next()

    def has_next_card(self):
        s = self.session
        return bool(s and isinstance(getattr(s, "next_info", None), dict) and self.layer("has", "next", timeout=2))

    def play_next(self, key=None):
        """OK sul riquadro "Episodio successivo" (o partenza automatica): lo apre."""
        s = self.session
        if not s or not isinstance(s.next_info, dict):
            return
        n = s.next_info
        log.info("episodio successivo: %s", n.get("ep"))
        self.play_episode(n["cat"], n, now=True)

    # ---------- barra di avanzamento ----------
    def seekbar(self, hold=None):
        """La barra di avanzamento dell'episodio (si aggiorna da sola finché è a schermo; in
        pausa resta)."""
        s = self.session
        if s and s.what == "episode":
            self.layer("seek", {"title": s.title, "hold": int((hold or 4) * 1000)}, timeout=3)
            return True
        return False

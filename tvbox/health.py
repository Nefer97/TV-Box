"""Sorveglianza delle dirette: il video avanza davvero? (decisione pura, provata dai test)

Stato per canale: Watch(canale, aperto_alle). Si chiama step() ogni 2 s con lo stato del video
letto dalla pagina (__tv.health()): restituisce True una sola volta, quando il video è fermo da
STALL secondi dopo la partenza (GRACE), senza che sia una pausa voluta dall'utente.
"""
GRACE = 25          # secondi per far partire il canale
STALL = 20          # secondi senza avanzare = fermo


class Watch:
    def __init__(self, cid, opened_at):
        self.cid, self.opened_at = cid, opened_at
        self.last_t, self.moved_at, self.done = None, opened_at, False

    def step(self, st, now):
        if self.done:
            return False
        t = (st or {}).get("t")
        if now - self.opened_at < GRACE or (st or {}).get("user") or (t is not None and t != self.last_t):
            self.last_t, self.moved_at = t, now
            return False
        if now - self.moved_at < STALL:
            return False
        self.done = True
        return True


def may_reopen(history, now, limit=3, window=600):
    """Riaperture recenti ancora ammesse? (al massimo `limit` in `window` secondi)"""
    recent = [t for t in history if now - t < window]
    return len(recent) < limit, recent

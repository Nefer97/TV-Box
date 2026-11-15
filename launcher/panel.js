// panel.js — pannello rapido sopra una diretta (MENU breve mentre si guarda un canale).
// tvd lo inietta solo quando serve e gli passa i dati; i tasti del telecomando arrivano da
// tvd (move/ok), la pagina sotto non li vede. Il video continua dietro.
//   __tvp.open({channels:[{id,label,color,title,start,end,image}], current, vol, videoLow})
//   __tvp.move('left'|'right'|'up'|'down')   __tvp.ok() -> azione per tvd   __tvp.close()
(function () {
  const V = 8;                       // versione: una più nuova sostituisce quella già caricata
  if (window.__tvp && window.__tvp.v === V) return;
  try { window.__tvp && window.__tvp.close(); } catch (e) {}
  const old = document.getElementById('__tvpanel'); if (old) old.remove();
  const CSS = `
  :host { all: initial; }
  /* stessi colori, caratteri e schede della home del launcher */
  .wrap { --bg1: #0b1020; --fg: #f4f6fb; --muted: #9aa3b8;
    position: fixed; left: 0; right: 0; bottom: 0; padding: 7vh 5vw 3.2vh;
    background: linear-gradient(to top, rgba(11,16,32,.97) 0%, rgba(11,16,32,.93) 62%, rgba(11,16,32,0) 100%);
    font-family: "Noto Sans", "DejaVu Sans", sans-serif; color: var(--fg); }
  .head { display: flex; align-items: center; margin: 0 0 1.4vh; }
  .h { font-size: 2.6vh; font-weight: 700; color: var(--muted); letter-spacing: .04em; text-transform: uppercase; }
  .h .dot { display: inline-block; width: 1.1vh; height: 1.1vh; border-radius: 50%;
    background: #ff3b3b; margin-right: .7vw; vertical-align: .15vh; }
  .clock { margin-left: auto; font-size: 3.4vh; font-weight: 800; letter-spacing: -.01em; }
  .viewport { overflow: hidden; padding: 1.4vh 1.2vw; margin: -1.4vh -1.2vw;
    -webkit-mask-image: linear-gradient(90deg, #000 0, #000 calc(100% - 5vw), transparent 100%); }
  .viewport.scrolled { -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 4vw, #000 calc(100% - 5vw), transparent 100%); }
  .viewport.scrolled.end { -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 4vw); }
  .viewport.end:not(.scrolled) { -webkit-mask-image: none; }
  .row { display: flex; gap: 1.4vw; transition: transform .2s ease-out; }
  .row::after { content: ""; flex: 0 0 .6vw; }   /* spazio per la cornice dell'ultima scheda */
  .card { flex: 0 0 18.5vw; height: 17vh; border-radius: 2.4vh; position: relative; overflow: hidden;
    padding: 1.5vh 1vw; box-sizing: border-box; display: flex; flex-direction: column; justify-content: flex-end;
    background: #1e293b center/cover no-repeat; color: #fff; box-shadow: 0 .8vh 2vh rgba(0,0,0,.35);
    transition: transform .15s ease, box-shadow .15s ease; }
  .card .shade { position: absolute; inset: 0;
    background: linear-gradient(180deg, rgba(0,0,0,.15) 15%, rgba(0,0,0,.88) 92%); }
  .card.noimg::before { content: attr(data-label); position: absolute; right: -.4vw; bottom: -2vh;
    font-size: 11vh; font-weight: 900; letter-spacing: -.03em; color: rgba(255,255,255,.08); white-space: nowrap; }
  .ch { position: absolute; top: 1.3vh; left: 1vw; font-size: 2.3vh; font-weight: 800;
    text-shadow: 0 .2vh .8vh rgba(0,0,0,.9); }
  .live { position: absolute; top: 1.6vh; right: 1vw; font-size: 1.6vh; font-weight: 700;
    background: #e11d2e; padding: .3vh .7vw; border-radius: 1vh; letter-spacing: .08em; }
  .card.cur .live { background: #fff; color: #0b1020; }
  .prog { position: relative; font-size: 2.1vh; font-weight: 700; line-height: 1.2;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .time { position: relative; font-size: 1.7vh; opacity: .85; margin-top: .4vh; }
  .bar { position: relative; height: .55vh; border-radius: .3vh; margin-top: .8vh;
    background: rgba(255,255,255,.25); overflow: hidden; }
  .bar i { display: block; height: 100%; background: #ff3b3b; }
  .card.f { transform: scale(1.07); box-shadow: 0 0 0 .5vh #fff, 0 2.4vh 5vh rgba(0,0,0,.6); z-index: 2; }
  .card.busy::after { content: "Apro…"; position: absolute; inset: 0; display: flex; align-items: center;
    justify-content: center; background: rgba(11,16,32,.7); font-size: 2.6vh; font-weight: 700; }
  .detail { margin-top: 2.4vh; min-height: 9vh; max-width: 70vw; }
  .dch { font-size: 2vh; font-weight: 700; color: #ff6b6b; letter-spacing: .06em; text-transform: uppercase; }
  .dtitle { font-size: 3.2vh; font-weight: 800; margin-top: .3vh; line-height: 1.15; }
  .ddesc { font-size: 2vh; line-height: 1.4; color: #d5d9e4; margin-top: .5vh;
    display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
  .btns { display: flex; gap: 1vw; margin-top: 2vh; }
  .b { font-size: 2.4vh; font-weight: 600; padding: 1.3vh 1.6vw; border-radius: 1.6vh; color: var(--fg);
    background: rgba(255,255,255,.07); white-space: nowrap; transition: transform .12s ease, background .12s; }
  .b .v { opacity: .8; margin-left: .6vw; font-weight: 500; }
  .b.f { background: #fff; color: #0b1020; transform: scale(1.03); }
  .hint { display: flex; gap: 2.6vw; margin-top: 2.2vh; font-size: 2vh; color: var(--muted); }
  .hint b { display: inline-block; color: #fff; background: rgba(255,255,255,.12); font-size: 1.8vh;
    padding: .35vh .8vw; border-radius: .9vh; margin-right: .5vw; letter-spacing: .03em;
    box-shadow: inset 0 -.25vh 0 rgba(0,0,0,.35); }
  /* schede-azione in fondo alla fila (come i riquadri piccoli della home) */
  .card.act { flex: 0 0 12.5vw; background: linear-gradient(160deg, #475569, #1e293b); }
  .card.act.home { background: linear-gradient(160deg, #334155, #0f172a); }
  .card.act.video { background: linear-gradient(160deg, #1d4ed8, #1e3a8a); }
  .act .ic { position: absolute; top: 1.5vh; left: 1vw; font-size: 4.2vh; line-height: 1; }
  .act .lbl { position: relative; font-size: 2.5vh; font-weight: 700; }
  .act .sub { position: relative; font-size: 1.7vh; opacity: .82; margin-top: .4vh; }
  /* volume: si regola con + e − del telecomando */
  .vol { display: flex; align-items: center; gap: .8vw; margin: 0 2.4vw 0 auto; font-size: 2.2vh;
    font-weight: 600; color: var(--muted); transition: color .15s; }
  .vol .vb { width: 11vw; height: 1vh; border-radius: .5vh; background: rgba(255,255,255,.18); overflow: hidden; }
  .vol .vb i { display: block; height: 100%; background: #3b82f6; border-radius: .5vh; transition: width .12s; }
  .vol .n { min-width: 3.6vw; text-align: right; }
  .vol.hot { color: #fff; }
  .clock { margin-left: 0; }`;

  let host = null, root = null, data = null, idx = 0, timer = 0, hot = 0, open = false;
  const TIMEOUT = 20000;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  const hhmm = ms => new Date(ms).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });

  // la fila: prima i canali, poi le azioni
  function entries() {
    const e = data.channels.map(ch => ({ kind: 'ch', ch }));
    if (data.videoLow != null)
      e.push({ kind: 'act', k: 'video', ic: '▣', lbl: 'Video', sub: data.videoLow ? 'più fluido' : 'come il menu',
               dch: 'Risoluzione durante i video', dtitle: data.videoLow ? 'Più fluido' : 'Come il menu',
               ddesc: 'OK per cambiare: "più fluido" abbassa la risoluzione mentre guardi, "come il menu" la lascia uguale.' });
    e.push({ kind: 'act', k: 'settings', ic: '⚙', lbl: 'Impostazioni', sub: 'Wi-Fi, schermo…',
             dch: 'Impostazioni', dtitle: 'Apri le impostazioni', ddesc: 'Il canale si chiude e si apre la pagina Impostazioni.' },
           { kind: 'act', k: 'home', ic: '⌂', lbl: 'Home', sub: 'Schermata iniziale',
             dch: 'Home', dtitle: 'Torna alla schermata iniziale', ddesc: 'Come tenere premuto MENU.' });
    return e;
  }

  function volBox() {
    const v = el('div', 'vol' + (hot ? ' hot' : ''));
    v.appendChild(el('span', '', '🔊'));
    const vb = el('span', 'vb'), i = el('i'); i.style.width = (data.vol || 0) + '%'; vb.appendChild(i);
    v.appendChild(vb);
    v.appendChild(el('span', 'n', data.vol != null ? data.vol + '%' : ''));
    return v;
  }

  function render() {
    if (!host) {
      host = document.createElement('div');
      host.id = '__tvpanel';
      host.setAttribute('popover', 'manual');
      host.style.cssText = 'all:initial;position:fixed;inset:auto 0 0 0;width:100vw;height:auto;' +
        'margin:0;padding:0;border:0;background:transparent;z-index:2147483647;overflow:visible';
      root = host.attachShadow({ mode: 'open' });
    }
    root.innerHTML = '';
    const st = el('style'); st.textContent = CSS; root.appendChild(st);
    const w = el('div', 'wrap');
    const head = el('div', 'head');
    const h = el('div', 'h'); h.appendChild(el('span', 'dot')); h.appendChild(document.createTextNode('Canali in diretta'));
    head.appendChild(h);
    head.appendChild(volBox());
    head.appendChild(el('div', 'clock', new Date().toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })));
    w.appendChild(head);
    const vp = el('div', 'viewport'), row = el('div', 'row');
    const now = Date.now();
    entries().forEach(x => {
      if (x.kind === 'act') {
        const card = el('div', 'card act ' + x.k);
        card.appendChild(el('div', 'ic', x.ic));
        card.appendChild(el('div', 'lbl', x.lbl));
        card.appendChild(el('div', 'sub', x.sub));
        row.appendChild(card);
        return;
      }
      const ch = x.ch, card = el('div', 'card');
      card.dataset.label = ch.label;
      if (ch.image) card.style.backgroundImage = `url("${ch.image.replace(/"/g, '%22')}")`;
      else { card.classList.add('noimg'); card.style.background = `linear-gradient(135deg, ${ch.color || '#334155'}, #0b1020)`; }
      if (ch.id === data.current) card.classList.add('cur');
      if (ch.id === data.busy) card.classList.add('busy');
      card.appendChild(el('div', 'shade'));
      card.appendChild(el('div', 'ch', ch.label));
      card.appendChild(el('div', 'live', ch.id === data.current ? 'IN VISIONE' : 'LIVE'));
      card.appendChild(el('div', 'prog', ch.title || ''));
      card.appendChild(el('div', 'time', ch.start && ch.end ? `${hhmm(ch.start)} – ${hhmm(ch.end)}` : ''));
      const bar = el('div', 'bar'), i = el('i');
      i.style.width = ch.start && ch.end > ch.start
        ? Math.max(0, Math.min(100, (now - ch.start) / (ch.end - ch.start) * 100)) + '%' : '0';
      bar.appendChild(i); card.appendChild(bar);
      row.appendChild(card);
    });
    vp.appendChild(row); w.appendChild(vp);
    const det = el('div', 'detail');
    ['dch', 'dtitle', 'ddesc'].forEach(k => det.appendChild(el('div', k)));
    w.appendChild(det);
    const hint = el('div', 'hint');
    hint.innerHTML = '<span><b>◄ ►</b>scegli</span><span><b>OK</b>cambia canale</span>' +
      '<span><b>+ −</b>volume</span><span><b>MENU</b>chiudi</span><span><b>Tieni MENU</b>home</span>';
    w.appendChild(hint);
    root.appendChild(w);
    // il popover sta nello strato più alto: si vede anche sopra un video a schermo intero
    const parent = document.body || document.documentElement;
    if (host.parentNode !== parent) parent.appendChild(host);
    try { if (!host.matches(':popover-open')) host.showPopover(); } catch (e) {}
    focus();
  }

  function focus() {
    const cards = root.querySelectorAll('.card'), list = entries();
    root.querySelectorAll('.f').forEach(e => e.classList.remove('f'));
    if (!cards.length) return;
    idx = Math.max(0, Math.min(cards.length - 1, idx));
    cards[idx].classList.add('f');
    const x = list[idx], det = root.querySelector('.detail');
    if (det && x) {
      const ch = x.ch;
      det.querySelector('.dch').textContent = ch ? ch.label + (ch.id === data.current ? ' · in visione' : '') : x.dch;
      det.querySelector('.dtitle').textContent = ch ? ch.title || '' : x.dtitle;
      det.querySelector('.ddesc').textContent = ch
        ? ch.desc || (ch.start && ch.end ? `${hhmm(ch.start)} – ${hhmm(ch.end)}` : '') : x.ddesc;
    }
    // la fila scorre per tenere visibile la scheda scelta
    const row = root.querySelector('.row'), vp = root.querySelector('.viewport');
    const card = cards[idx], max = Math.max(0, row.scrollWidth - vp.clientWidth);
    const off = Math.max(0, Math.min(max, card.offsetLeft - vp.clientWidth / 2 + card.offsetWidth / 2));
    row.style.transform = `translateX(${-off}px)`;
    vp.classList.toggle('scrolled', off > 0);
    vp.classList.toggle('end', off >= max - 1);
  }
  function arm() {
    clearTimeout(timer);
    timer = setTimeout(close, TIMEOUT);
  }

  function close() {
    clearTimeout(timer);
    open = false;
    if (host) {
      try { host.hidePopover(); } catch (e) {}
      host.remove();
    }
  }

  // un elemento messo a schermo intero dopo il pannello gli passerebbe sopra: lo rimetto in cima
  document.addEventListener('fullscreenchange', () => {
    if (!open || !host) return;
    try { host.hidePopover(); host.showPopover(); } catch (e) {}
  }, true);

  window.__tvp = {
    v: V,
    open(d) {
      data = d;
      const i = d.channels.findIndex(x => x.id === d.current);
      idx = i < 0 ? 0 : i;
      open = true;
      render();
      arm();
      return true;
    },
    close() { close(); return true; },
    isOpen() { return open && !!host && host.isConnected; },
    move(d) {
      if (!open) return false;
      arm();
      if (d === 'left' || d === 'right') {   // la fila gira in cerchio: dal primo all'ultimo e viceversa
        const n = entries().length;
        idx = (idx + (d === 'left' ? -1 : 1) + n) % n;
        focus();
      }
      return true;
    },
    ok() {
      if (!open) return null;
      arm();
      const x = entries()[idx];
      if (!x) return null;
      if (x.kind === 'ch') return { act: 'open', id: x.ch.id };
      if (x.k === 'video') return { act: 'video', on: !data.videoLow };
      return { act: x.k };
    },
    set(k, v) {                     // aggiorna un valore senza perdere la scheda scelta
      if (!open) return false;
      arm();
      data[k] = v;
      if (k === 'vol') {            // solo l'indicatore: niente ridisegno (le immagini non lampeggiano)
        hot = 1;
        const old = root.querySelector('.vol');
        if (old) old.replaceWith(volBox());
        clearTimeout(window.__tvpHot);
        window.__tvpHot = setTimeout(() => { hot = 0; const o = root && root.querySelector('.vol'); if (o) o.classList.remove('hot'); }, 1200);
        return true;
      }
      render();
      return true;
    }
  };
})();

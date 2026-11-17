// layer.js — lo "strato TV": tutto ciò che compare sopra le pagine dei servizi.
//
//   sipario   fondo blu con "Apro Rai 1…" finché il video nuovo non va a tutto schermo
//   pannello  cambio canale sopra la diretta (MENU, ◄ ►): schede come la home + azioni
//   banner    programma in onda all'apertura di un canale (6 s)
//   volume    barra in alto a destra a ogni + −
//   avviso    messaggio breve in basso ("Pausa", "La diretta si è fermata…")
//
// Un solo elemento (popover: sta sopra anche al video a schermo intero) con un'ombra (shadow
// DOM: lo stile del sito non lo tocca) e lo stile comune della home (window.__tvCardsCSS +
// js/cards.js, aggiunti da tvd davanti a questo file). I tasti li riceve tvd e li passa qui.
//
//   __tvl.boot({curtain, panel})  prenotato da tvd nella pagina che sta per nascere
//   __tvl.curtain(etichetta)      __tvl.panel(dati)  __tvl.move(dir)  __tvl.ok()  __tvl.set(k, v)
//   __tvl.closePanel()  __tvl.has('panel'|'curtain')  __tvl.banner(dati)  __tvl.volume(v)  __tvl.toast(testo)
(function () {
  const V = 1;                        // versione: una più nuova sostituisce quella già caricata
  if (window.top !== window) return;  // solo nella pagina principale, non nei riquadri interni
  if (window.__tvl && window.__tvl.v === V) return;
  try { window.__tvl && window.__tvl.destroy(); } catch (e) {}
  const C = window.TVCards;

  const CSS = `
  :host { all: initial; }
  .layer { position: fixed; inset: 0; pointer-events: none; font-family: var(--font); color: var(--fg); }
  /* sipario */
  .curtain { position: absolute; inset: 0; transition: opacity .6s ease;
    background: radial-gradient(120% 120% at 20% 0%, var(--bg2), var(--bg1)); }
  .curtain.gone { opacity: 0; }
  .curtain .load { position: absolute; left: 0; right: 0; top: 24vh; display: flex; flex-direction: column;
    align-items: center; gap: 2.4vh; font-size: 3vh; font-weight: 700; }
  .spin { width: 8vh; height: 8vh; border-radius: 50%; border: .8vh solid rgba(255,255,255,.18);
    border-top-color: #fff; animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  /* pannello */
  .panel { position: absolute; left: 0; right: 0; bottom: 0; padding: 7vh 5vw 3.2vh; --card-h: 17vh;
    background: linear-gradient(to top, rgba(11,16,32,.97) 0%, rgba(11,16,32,.93) 62%, rgba(11,16,32,0) 100%); }
  .head { display: flex; align-items: center; margin: 0 0 1.4vh; }
  .clock { margin-left: auto; font-size: 3.4vh; font-weight: 800; letter-spacing: -.01em; }
  .viewport { overflow: hidden; padding: 1.4vh 1.2vw; margin: -1.4vh -1.2vw;
    -webkit-mask-image: linear-gradient(90deg, #000 0, #000 calc(100% - 5vw), transparent 100%); }
  .viewport.scrolled { -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 4vw, #000 calc(100% - 5vw), transparent 100%); }
  .viewport.scrolled.end { -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 4vw); }
  .viewport.end:not(.scrolled) { -webkit-mask-image: none; }
  .row { display: flex; gap: 1.4vw; transition: transform .2s ease-out; }
  .row::after { content: ""; flex: 0 0 .6vw; }   /* spazio per la cornice dell'ultima scheda */
  .tvcard.act.home { background: linear-gradient(160deg, #334155, #0f172a); }
  .tvcard.act.video { background: linear-gradient(160deg, #1d4ed8, #1e3a8a); }
  .tvcard.act.guide { background: linear-gradient(160deg, #0f766e, #134e4a); }
  .tvcard.act.sleep { background: linear-gradient(160deg, #6d28d9, #3b0764); }
  .detail { margin-top: 2.4vh; min-height: 9vh; max-width: 70vw; }
  .detail .dtitle { font-size: 3.2vh; }
  .detail .ddesc { -webkit-line-clamp: 1; font-size: 2vh; margin-top: .5vh; }
  .keys { margin-top: 2.2vh; }
  /* banner del programma */
  .osd { position: absolute; left: 4vw; right: 4vw; bottom: 5vh; display: flex; gap: 2vw; align-items: center;
    padding: 2.2vh 2vw; border-radius: 2.6vh;
    background: linear-gradient(90deg, rgba(11,16,32,.94), rgba(11,16,32,.82));
    box-shadow: 0 2vh 5vh rgba(0,0,0,.55); opacity: 0; transform: translateY(2vh);
    transition: opacity .35s ease, transform .35s ease; }
  .osd.in { opacity: 1; transform: none; }
  .osd .pic { flex: 0 0 18vw; height: 10.1vw; border-radius: 1.6vh; background: #1e293b center/cover no-repeat; }
  .osd .txt { flex: 1; min-width: 0; }
  .osd .ch { font-size: 2.2vh; font-weight: 700; color: #ff6b6b; letter-spacing: .06em; text-transform: uppercase; }
  .osd .live { display: inline-block; margin-left: 1vw; font-size: 1.6vh; padding: .2vh .6vw; border-radius: .8vh;
    background: var(--live); color: #fff; letter-spacing: .08em; vertical-align: .2vh; }
  .osd .title { font-size: 4vh; font-weight: 800; line-height: 1.12; margin-top: .4vh;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .osd .time { display: flex; align-items: center; gap: 1.2vw; margin-top: 1.2vh; font-size: 2.2vh; color: var(--muted); }
  .osd .bar { flex: 0 0 22vw; height: .7vh; border-radius: .4vh; background: rgba(255,255,255,.2); overflow: hidden; }
  .osd .bar i { display: block; height: 100%; background: var(--live-bar); }
  .osd .next { margin-top: 1.2vh; font-size: 2.1vh; color: #d5d9e4; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .osd .next b { color: var(--muted); font-weight: 600; margin-right: .6vw; }
  /* volume */
  .vol { position: absolute; top: 6vh; right: 4vw; display: flex; align-items: center; gap: 1.4vw;
    padding: 1.8vh 1.8vw; border-radius: 2.4vh; background: rgba(11,16,32,.9); box-shadow: 0 1.6vh 4vh rgba(0,0,0,.5);
    opacity: 0; transform: translateY(-1.5vh); transition: opacity .2s ease, transform .2s ease; }
  .vol.in { opacity: 1; transform: none; }
  .vol svg { width: 4vh; height: 4vh; flex: 0 0 auto; }
  .vol .bar { width: 18vw; height: 1.1vh; border-radius: .6vh; background: rgba(255,255,255,.18); overflow: hidden; }
  .vol .bar i { display: block; height: 100%; border-radius: .6vh; background: var(--accent); transition: width .12s ease; }
  .vol .n { min-width: 4.5vw; text-align: right; font-size: 3.2vh; font-weight: 800; font-variant-numeric: tabular-nums; }
  /* avviso */
  .toast { position: absolute; left: 50%; bottom: 9vh; transform: translateX(-50%); white-space: nowrap;
    background: rgba(11,16,32,.9); font-size: 3.2vh; font-weight: 700; line-height: 1.2;
    padding: 1.8vh 2.6vw; border-radius: 2.4vh; box-shadow: 0 1.6vh 4vh rgba(0,0,0,.5);
    opacity: 0; transition: opacity .25s; }
  .toast.in { opacity: 1; }`;

  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const clock = () => new Date().toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });

  // ---------- l'elemento unico in cima alla pagina ----------
  let host = null, root = null, box = null, guard = 0;
  const parts = {};                   // curtain, panel, osd, vol, toast: i pezzi a schermo

  function mount() {
    if (!host) {
      host = document.createElement('div');
      host.id = '__tvlayer';
      host.setAttribute('popover', 'manual');
      host.style.cssText = 'all:initial;position:fixed;inset:0;width:100vw;height:100vh;margin:0;padding:0;' +
        'border:0;background:transparent;z-index:2147483647;overflow:visible;pointer-events:none';
      root = host.attachShadow({ mode: 'open' });
      root.appendChild(el('style', '', (window.__tvCardsCSS || '') + CSS));
      box = el('div', 'layer');
      root.appendChild(box);
    }
    // rimesso solo se la pagina l'ha tolto: spostarlo lo farebbe sparire e ricomparire (lampeggio)
    if (!host.isConnected) (document.body || document.documentElement).appendChild(host);
    try { if (!host.matches(':popover-open')) host.showPopover(); } catch (e) {}
    // alcune app (RaiPlay) ridisegnano tutta la pagina mentre partono: lo strato si rimette a posto
    // (finché c'è qualcosa a schermo, anche un pezzo che sta sfumando)
    if (!guard) guard = setInterval(() => { if (box.childElementCount) mount(); else unmount(); }, 300);
  }
  function unmount() {
    clearInterval(guard); guard = 0;
    if (host) { try { host.hidePopover(); } catch (e) {} host.remove(); }
  }
  // i pezzi stanno in un ordine fisso: il sipario sotto, il pannello sopra, gli avvisi in cima
  const ORDER = ['curtain', 'osd', 'panel', 'vol', 'toast'];
  function put(name, node) {
    drop(name);
    parts[name] = node;
    mount();
    const after = ORDER.slice(ORDER.indexOf(name) + 1).map(n => parts[n]).find(Boolean);
    box.insertBefore(node, after || null);
    return node;
  }
  function drop(name) {
    const n = parts[name];
    delete parts[name];
    if (n) n.remove();
  }
  // un elemento messo a schermo intero dopo lo strato gli passerebbe sopra: lo rimetto in cima
  const onFull = () => { if (host && host.isConnected) { try { host.hidePopover(); host.showPopover(); } catch (e) {} } };
  document.addEventListener('fullscreenchange', onFull, true);

  // ---------- sipario ----------
  // resta finché il video nuovo va ed è a tutto schermo, più un secondo (lo schermo intero
  // arriva con un attimo di ritardo); al massimo 15 s
  let curtainT = 0;
  function curtain(label) {
    clearInterval(curtainT);
    const cu = el('div', 'curtain'), ld = el('div', 'load');
    ld.append(el('div', 'spin'), el('div', '', 'Apro ' + (label || 'il canale') + '…'));
    cu.appendChild(ld);
    put('curtain', cu);
    const t0 = Date.now();
    let readyAt = 0;
    curtainT = setInterval(() => {
      const playing = [...document.querySelectorAll('video')].some(v => !v.paused && v.readyState >= 3 && v.currentTime > 0);
      const big = !window.__tv || window.__tv.isPlayer();
      readyAt = playing && big ? readyAt || Date.now() : 0;
      if (!(readyAt && Date.now() - readyAt >= 1000) && Date.now() - t0 < 15000) return;
      liftCurtain();
    }, 250);
    return true;
  }
  function liftCurtain() {
    clearInterval(curtainT);
    const c = parts.curtain;
    if (!c) return;
    delete parts.curtain;
    c.classList.add('gone');
    setTimeout(() => c.remove(), 700);
    document.documentElement.style.removeProperty('background');   // il colore messo da boot()
  }

  // ---------- pannello cambio canale ----------
  //   dati: {channels:[{id,label,color,title,start,end,image,desc}], current, busy, step, videoLow, sleep}
  let data = null, idx = 0, panelT = 0;
  const PANEL_TIMEOUT = 20000;

  // la fila: prima i canali, poi le azioni
  function entries() {
    const e = data.channels.map(ch => ({ ch }));
    if (data.videoLow != null) {
      e.push({ k: 'video', ic: '▣', lbl: 'Video', sub: data.videoLow ? 'più fluido' : 'come il menu',
        dch: 'Risoluzione durante i video', dtitle: data.videoLow ? 'Più fluido' : 'Come il menu',
        ddesc: 'OK per cambiare: "più fluido" abbassa la risoluzione mentre guardi, "come il menu" la lascia uguale.' });
    }
    const sl = data.sleep || 0;
    e.push({ k: 'guide', ic: '☰', lbl: 'Guida TV', sub: 'Cosa c\'è dopo',
      dch: 'Guida TV', dtitle: 'I programmi delle prossime ore', ddesc: 'Il canale si chiude e si apre la Guida TV.' },
    { k: 'sleep', ic: '◷', lbl: 'Timer', sub: sl ? `spegne tra ${sl} min` : 'spento',
      dch: 'Timer di spegnimento', dtitle: sl ? `Lo schermo si spegne tra ${sl} minuti` : 'Timer spento',
      ddesc: 'OK per cambiare: 30, 60, 90, 120 minuti o spento. Un tasto qualsiasi riaccende lo schermo.' },
    { k: 'settings', ic: '⚙', lbl: 'Impostazioni', sub: 'Wi-Fi, schermo…',
      dch: 'Impostazioni', dtitle: 'Apri le impostazioni', ddesc: 'Il canale si chiude e si apre la pagina Impostazioni.' },
    { k: 'home', ic: '⌂', lbl: 'Home', sub: 'Schermata iniziale',
      dch: 'Home', dtitle: 'Torna alla schermata iniziale', ddesc: 'Come tenere premuto MENU.' });
    return e;
  }

  function renderPanel() {
    const w = el('div', 'panel'), head = el('div', 'head'), h = el('div', 'sec-title');
    h.appendChild(el('span', 'dot'));
    h.appendChild(document.createTextNode('Canali in diretta'));
    head.append(h, el('div', 'clock', clock()));
    const vp = el('div', 'viewport'), row = el('div', 'row'), now = Date.now();
    entries().forEach(x => {
      if (!x.ch) { row.appendChild(C.action(x)); return; }
      const c = C.live(x.ch, { current: x.ch.id === data.current, busy: x.ch.id === data.busy });
      C.fill(c, x.ch, now);
      row.appendChild(c);
    });
    vp.appendChild(row);
    const det = el('div', 'detail');
    ['dch', 'dtitle', 'ddesc'].forEach(k => det.appendChild(el('div', k)));
    const keys = el('div', 'keys');
    keys.innerHTML = '<span><b>◄ ►</b>scegli</span><span><b>OK</b>cambia canale</span>' +
      '<span><b>+ −</b>volume</span><span><b>MENU</b>chiudi</span><span><b>Tieni MENU</b>home</span>';
    w.append(head, vp, det, keys);
    put('panel', w);
    focus();
  }

  function focus() {
    const w = parts.panel;
    if (!w) return;
    const cards = w.querySelectorAll('.tvcard'), list = entries();
    w.querySelectorAll('.f').forEach(e => e.classList.remove('f'));
    if (!cards.length) return;
    idx = Math.max(0, Math.min(cards.length - 1, idx));
    cards[idx].classList.add('f');
    const x = list[idx], det = w.querySelector('.detail'), ch = x && x.ch;
    if (det && x) {
      det.querySelector('.dch').textContent = ch ? ch.label + (ch.id === data.current ? ' · in visione' : '') : x.dch;
      det.querySelector('.dtitle').textContent = ch ? ch.title || '' : x.dtitle;
      det.querySelector('.ddesc').textContent = ch ? ch.desc || C.span(ch) : x.ddesc;
    }
    // la fila scorre tenendo la scheda scelta al centro
    const row = w.querySelector('.row'), vp = w.querySelector('.viewport'), card = cards[idx];
    const max = Math.max(0, row.scrollWidth - vp.clientWidth);
    const off = Math.max(0, Math.min(max, card.offsetLeft - vp.clientWidth / 2 + card.offsetWidth / 2));
    row.style.transform = `translateX(${-off}px)`;
    vp.classList.toggle('scrolled', off > 0);
    vp.classList.toggle('end', off >= max - 1);
  }
  function arm() { clearTimeout(panelT); panelT = setTimeout(closePanel, PANEL_TIMEOUT); }
  function panel(d) {
    hideBanner();
    data = d;
    const i = d.channels.findIndex(x => x.id === d.current), n = d.channels.length;
    // ◄ ► sulla diretta: si apre già sul canale vicino (in cerchio tra i canali)
    idx = i < 0 ? 0 : (n ? ((i + (d.step || 0)) % n + n) % n : 0);
    renderPanel();
    arm();
    return true;
  }
  function closePanel() {
    clearTimeout(panelT);
    drop('panel');
    data = null;
    return true;
  }

  // ---------- banner del programma ----------
  //   dati: {label, now: {title, start, end, image}, next: {title, start}}
  let osdT = 0;
  function banner(d, tries) {
    if (!d || !d.now || !d.now.title || parts.panel) return false;    // c'è il pannello: niente banner
    if (parts.curtain && (tries || 0) < 12) {                         // c'è ancora il sipario: aspetto
      setTimeout(() => banner(d, (tries || 0) + 1), 400);
      return true;
    }
    const o = el('div', 'osd');
    if (d.now.image) {
      const pic = el('div', 'pic');
      pic.style.backgroundImage = `url("${d.now.image.replace(/"/g, '%22')}")`;
      o.appendChild(pic);
    }
    const txt = el('div', 'txt'), ch = el('div', 'ch', d.label);
    ch.appendChild(el('span', 'live', 'LIVE'));
    txt.append(ch, el('div', 'title', d.now.title));
    const time = el('div', 'time', C.span(d.now)), bar = el('div', 'bar'), i = el('i');
    i.style.width = C.progress(d.now) + '%';
    bar.appendChild(i);
    if (d.now.start && d.now.end) time.appendChild(bar);
    txt.appendChild(time);
    if (d.next && d.next.title) {
      const n = el('div', 'next');
      n.append(el('b', '', 'Dopo, alle ' + C.hhmm(d.next.start)), document.createTextNode(d.next.title));
      txt.appendChild(n);
    }
    o.appendChild(txt);
    put('osd', o);
    requestAnimationFrame(() => requestAnimationFrame(() => o.classList.add('in')));
    clearTimeout(osdT);
    osdT = setTimeout(hideBanner, 6000);
    return true;
  }
  function hideBanner() {
    clearTimeout(osdT);
    fade('osd', 400);
  }
  // un pezzo che sparisce con una dissolvenza (tolto davvero solo se nel frattempo non è cambiato)
  function fade(name, ms) {
    const n = parts[name];
    if (!n) return;
    n.classList.remove('in');
    setTimeout(() => { if (parts[name] === n) drop(name); }, ms);
  }

  // ---------- barra del volume ----------
  const SPK = '<path d="M11 5 6 9H2v6h4l5 4z" fill="currentColor"/>';
  const WAVES = '<path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>';
  const MUTE = '<path d="M16 9l5 6M21 9l-5 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>';
  let volT = 0;
  function volume(v, ms) {
    if (v == null) { clearTimeout(volT); fade('vol', 150); return true; }   // chiudi subito
    v = Math.max(0, Math.min(100, Math.round(v)));
    let b = parts.vol;
    if (!b) {
      b = el('div', 'vol');
      b.innerHTML = '<svg viewBox="0 0 24 24"></svg><div class="bar"><i></i></div><div class="n"></div>';
      put('vol', b);
    }
    b.querySelector('svg').innerHTML = SPK + (v ? WAVES : MUTE);
    b.querySelector('.bar i').style.width = v + '%';
    b.querySelector('.n').textContent = v;
    requestAnimationFrame(() => b.classList.add('in'));
    clearTimeout(volT);
    volT = setTimeout(() => fade('vol', 250), ms || 2000);
    return true;
  }

  // ---------- avviso ----------
  let toastT = 0;
  function toast(msg) {
    const t = parts.toast || put('toast', el('div', 'toast'));
    t.textContent = msg;
    requestAnimationFrame(() => t.classList.add('in'));
    clearTimeout(toastT);
    toastT = setTimeout(() => fade('toast', 300), 1800);
    return true;
  }

  // ---------- prenotazione: la pagina nuova nasce già con sipario e/o pannello ----------
  // Nel primo istante della pagina l'elemento radice non c'è ancora: lo si aspetta e lo si
  // colora di blu, senza aspettare il corpo della pagina (che su Mediaset arriva tardi).
  function boot(d) {
    const start = () => {
      const e = document.documentElement;
      if (!e) return false;
      e.style.setProperty('background', '#0b1020', 'important');
      try {
        if (d.curtain) curtain(d.curtain);
        if (d.panel) panel(d.panel);
      } catch (x) { console.error('[strato TV]', x); }
      return true;
    };
    if (!start()) {
      const mo = new MutationObserver(() => { if (start()) mo.disconnect(); });
      mo.observe(document, { childList: true });
    }
    return true;
  }

  window.__tvl = {
    v: V, boot, curtain, banner, volume, toast,
    panel, closePanel,
    has: name => !!parts[name],
    move(d) {                        // la fila gira in cerchio
      if (!parts.panel) return false;
      arm();
      const n = entries().length;
      idx = (idx + (d === 'left' ? -1 : 1) + n) % n;
      focus();
      return true;
    },
    ok() {
      if (!parts.panel) return null;
      arm();
      const x = entries()[idx];
      if (!x) return null;
      if (x.ch) return { act: 'open', id: x.ch.id };
      if (x.k === 'video') return { act: 'video', on: !data.videoLow };
      return { act: x.k };
    },
    set(k, v) {                      // aggiorna un valore del pannello (busy, videoLow, sleep)
      if (!parts.panel) return false;
      arm();
      data[k] = v;
      renderPanel();
      return true;
    },
    destroy() {
      [curtainT, panelT, osdT, volT, toastT].forEach(t => { clearTimeout(t); clearInterval(t); });
      document.removeEventListener('fullscreenchange', onFull, true);
      Object.keys(parts).forEach(drop);
      unmount();
    },
  };
})();

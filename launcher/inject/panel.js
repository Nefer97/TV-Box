// panel.js — pannello cambio canale sopra una diretta (MENU breve mentre si guarda un canale).
// tvd lo inietta solo quando serve, insieme a js/cards.js (le schede, uguali alla home) e
// allo stile css/tokens.css + css/cards.css (window.__tvCardsCSS). I tasti arrivano da tvd:
// la pagina sotto non li vede e il video continua dietro.
//   __tvp.open({channels:[{id,label,color,title,start,end,image,desc}], current, vol, videoLow})
//   __tvp.move('left'|'right')   __tvp.ok() -> azione per tvd   __tvp.set(chiave, valore)   __tvp.close()
(function () {
  const V = 11;                       // versione: una più nuova sostituisce quella già caricata
  if (window.__tvp && window.__tvp.v === V) return;
  try { window.__tvp && window.__tvp.close(); } catch (e) {}
  const old = document.getElementById('__tvpanel');
  if (old) old.remove();
  const C = window.TVCards;

  // solo quello che è del pannello: le schede hanno lo stile comune (cards.css)
  const CSS = `
  :host { all: initial; }
  /* sipario: copre la pagina nuova (es. Mediaset parte bianca) finché il video non parte */
  .curtain { position: fixed; inset: 0; transition: opacity .6s ease;
    background: radial-gradient(120% 120% at 20% 0%, var(--bg2), var(--bg1)); }
  .curtain.gone { opacity: 0; }
  .wrap { position: fixed; left: 0; right: 0; bottom: 0; padding: 7vh 5vw 3.2vh; --card-h: 17vh;
    background: linear-gradient(to top, rgba(11,16,32,.97) 0%, rgba(11,16,32,.93) 62%, rgba(11,16,32,0) 100%);
    font-family: var(--font); color: var(--fg); }
  .head { display: flex; align-items: center; margin: 0 0 1.4vh; }
  .clock { font-size: 3.4vh; font-weight: 800; letter-spacing: -.01em; }
  .viewport { overflow: hidden; padding: 1.4vh 1.2vw; margin: -1.4vh -1.2vw;
    -webkit-mask-image: linear-gradient(90deg, #000 0, #000 calc(100% - 5vw), transparent 100%); }
  .viewport.scrolled { -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 4vw, #000 calc(100% - 5vw), transparent 100%); }
  .viewport.scrolled.end { -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 4vw); }
  .viewport.end:not(.scrolled) { -webkit-mask-image: none; }
  .row { display: flex; gap: 1.4vw; transition: transform .2s ease-out; }
  .row::after { content: ""; flex: 0 0 .6vw; }   /* spazio per la cornice dell'ultima scheda */
  .tvcard.act.home { background: linear-gradient(160deg, #334155, #0f172a); }
  .tvcard.act.video { background: linear-gradient(160deg, #1d4ed8, #1e3a8a); }
  .detail { margin-top: 2.4vh; min-height: 9vh; max-width: 70vw; }
  .detail .dtitle { font-size: 3.2vh; }
  .detail .ddesc { -webkit-line-clamp: 1; font-size: 2vh; margin-top: .5vh; }
  .keys { margin-top: 2.2vh; }
  /* volume: si regola con + e − del telecomando */
  .vol { display: flex; align-items: center; gap: .8vw; margin: 0 2.4vw 0 auto; font-size: 2.2vh;
    font-weight: 600; color: var(--muted); transition: color .15s; }
  .vol .vb { width: 11vw; height: 1vh; border-radius: .5vh; background: rgba(255,255,255,.18); overflow: hidden; }
  .vol .vb i { display: block; height: 100%; background: var(--accent); border-radius: .5vh; transition: width .12s; }
  .vol .n { min-width: 3.6vw; text-align: right; }
  .vol.hot { color: #fff; }`;

  let host = null, root = null, data = null, idx = 0, timer = 0, hot = false, hotT = 0, open = false;
  const TIMEOUT = 20000;
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const clock = () => new Date().toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });

  // la fila: prima i canali, poi le azioni
  function entries() {
    const e = data.channels.map(ch => ({ ch }));
    if (data.videoLow != null) {
      e.push({ k: 'video', ic: '▣', lbl: 'Video', sub: data.videoLow ? 'più fluido' : 'come il menu',
        dch: 'Risoluzione durante i video', dtitle: data.videoLow ? 'Più fluido' : 'Come il menu',
        ddesc: 'OK per cambiare: "più fluido" abbassa la risoluzione mentre guardi, "come il menu" la lascia uguale.' });
    }
    e.push({ k: 'settings', ic: '⚙', lbl: 'Impostazioni', sub: 'Wi-Fi, schermo…',
      dch: 'Impostazioni', dtitle: 'Apri le impostazioni', ddesc: 'Il canale si chiude e si apre la pagina Impostazioni.' },
    { k: 'home', ic: '⌂', lbl: 'Home', sub: 'Schermata iniziale',
      dch: 'Home', dtitle: 'Torna alla schermata iniziale', ddesc: 'Come tenere premuto MENU.' });
    return e;
  }

  function volBox() {
    const v = el('div', 'vol' + (hot ? ' hot' : ''));
    v.appendChild(el('span', '', '🔊'));
    const vb = el('span', 'vb'), i = el('i');
    i.style.width = (data.vol || 0) + '%';
    vb.appendChild(i);
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
    root.appendChild(el('style', '', (window.__tvCardsCSS || '') + CSS));
    const w = el('div', 'wrap'), head = el('div', 'head');
    const h = el('div', 'sec-title');
    h.appendChild(el('span', 'dot'));
    h.appendChild(document.createTextNode('Canali in diretta'));
    head.append(h, volBox(), el('div', 'clock', clock()));
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
    if (data.curtain) root.appendChild(el('div', 'curtain'));
    root.appendChild(w);
    // il popover sta nello strato più alto: si vede anche sopra un video a schermo intero
    const parent = document.body || document.documentElement;
    if (host.parentNode !== parent) parent.appendChild(host);
    try { if (!host.matches(':popover-open')) host.showPopover(); } catch (e) {}
    focus();
  }

  function focus() {
    const cards = root.querySelectorAll('.tvcard'), list = entries();
    root.querySelectorAll('.f').forEach(e => e.classList.remove('f'));
    if (!cards.length) return;
    idx = Math.max(0, Math.min(cards.length - 1, idx));
    cards[idx].classList.add('f');
    const x = list[idx], det = root.querySelector('.detail'), ch = x && x.ch;
    if (det && x) {
      det.querySelector('.dch').textContent = ch ? ch.label + (ch.id === data.current ? ' · in visione' : '') : x.dch;
      det.querySelector('.dtitle').textContent = ch ? ch.title || '' : x.dtitle;
      det.querySelector('.ddesc').textContent = ch ? ch.desc || C.span(ch) : x.ddesc;
    }
    // la fila scorre per tenere visibile la scheda scelta
    const row = root.querySelector('.row'), vp = root.querySelector('.viewport'), card = cards[idx];
    const max = Math.max(0, row.scrollWidth - vp.clientWidth);
    const off = Math.max(0, Math.min(max, card.offsetLeft - vp.clientWidth / 2 + card.offsetWidth / 2));
    row.style.transform = `translateX(${-off}px)`;
    vp.classList.toggle('scrolled', off > 0);
    vp.classList.toggle('end', off >= max - 1);
  }
  function arm() { clearTimeout(timer); timer = setTimeout(close, TIMEOUT); }
  // alcune app (RaiPlay) ridisegnano tutta la pagina mentre partono: il pannello si rimette a posto
  let guard = 0;
  function keep() {
    clearInterval(guard);
    guard = setInterval(() => {
      if (!open || !host || host.isConnected) return;
      (document.body || document.documentElement).appendChild(host);
      try { host.showPopover(); } catch (e) {}
    }, 300);
  }
  let curtainT = 0;
  function watchCurtain() {
    clearInterval(curtainT);
    if (!data.curtain) return;
    const t0 = Date.now();
    curtainT = setInterval(() => {
      const playing = [...document.querySelectorAll('video')].some(v => !v.paused && v.readyState >= 3 && v.currentTime > 0);
      if (!playing && Date.now() - t0 < 12000) return;
      clearInterval(curtainT);
      data.curtain = false;
      const c = root && root.querySelector('.curtain');
      if (c) { c.classList.add('gone'); setTimeout(() => c.remove(), 700); }
    }, 300);
  }
  function close() {
    clearTimeout(timer);
    clearInterval(guard);
    clearInterval(curtainT);
    open = false;
    if (host) { try { host.hidePopover(); } catch (e) {} host.remove(); }
  }

  // un elemento messo a schermo intero dopo il pannello gli passerebbe sopra: lo rimetto in cima
  document.addEventListener('fullscreenchange', () => {
    if (open && host) { try { host.hidePopover(); host.showPopover(); } catch (e) {} }
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
      keep();
      watchCurtain();
      return true;
    },
    close() { close(); return true; },
    isOpen() { return open && !!host; },        // se la pagina lo toglie, keep() lo rimette
    move(d) {                        // la fila gira in cerchio
      if (!open) return false;
      arm();
      const n = entries().length;
      idx = (idx + (d === 'left' ? -1 : 1) + n) % n;
      focus();
      return true;
    },
    ok() {
      if (!open) return null;
      arm();
      const x = entries()[idx];
      if (!x) return null;
      if (x.ch) return { act: 'open', id: x.ch.id };
      if (x.k === 'video') return { act: 'video', on: !data.videoLow };
      return { act: x.k };
    },
    set(k, v) {                      // aggiorna un valore senza perdere la scheda scelta
      if (!open) return false;
      arm();
      data[k] = v;
      if (k !== 'vol') { render(); return true; }
      hot = true;                    // solo l'indicatore del volume: le immagini non lampeggiano
      const o = root.querySelector('.vol');
      if (o) o.replaceWith(volBox());
      clearTimeout(hotT);
      hotT = setTimeout(() => { hot = false; const e = root && root.querySelector('.vol'); if (e) e.classList.remove('hot'); }, 1200);
      return true;
    },
  };
})();

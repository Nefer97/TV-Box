// nav.js — "navigazione assistita" nei siti: le frecce del telecomando saltano da un elemento
// cliccabile all'altro (riquadro ben visibile), OK lo apre, nei campi di testo apre la tastiera
// a schermo. Se in una direzione non c'è niente, la pagina scorre.
// Iniettato da tvd in ogni pagina; non fa nulla finché tvd non chiama __nav.move()/activate().
(function () {
  if (window.__nav) return;

  const SEL = 'a[href], button, input:not([type=hidden]), select, textarea, summary, ' +
    '[role=button], [role=link], [role=tab], [role=menuitem], [role=option], [role=checkbox], ' +
    '[role=switch], [contenteditable=""], [contenteditable=true], [tabindex]:not([tabindex="-1"]), ' +
    '[onclick], label[for]';
  const TEXT_TYPES = /^(text|search|email|url|tel|password|number|)$/i;
  let cur = null, ring = null, raf = 0;

  // ---------- riquadro ----------
  function ensureRing() {
    if (ring && ring.isConnected) return ring;
    ring = document.createElement('div');
    ring.id = '__nav_ring';
    ring.style.cssText = 'position:fixed;z-index:2147483646;pointer-events:none;border-radius:10px;' +
      'border:4px solid #ffd400;box-shadow:0 0 0 3px rgba(0,0,0,.65),0 0 24px 6px rgba(255,212,0,.55);' +
      'transition:left .12s,top .12s,width .12s,height .12s;display:none';
    (document.body || document.documentElement).appendChild(ring);
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return ring;
  }
  function place() {
    if (!ring) return;
    if (!cur || !cur.isConnected) { ring.style.display = 'none'; return; }
    const r = cur.getBoundingClientRect(), m = 6;
    Object.assign(ring.style, { display: 'block', left: (r.left - m) + 'px', top: (r.top - m) + 'px',
      width: (r.width + 2 * m) + 'px', height: (r.height + 2 * m) + 'px' });
  }
  function hide() { if (ring) ring.style.display = 'none'; }

  // ---------- elementi candidati ----------
  function visible(el, r) {
    if (r.width < 6 || r.height < 6) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) return false;
    if (el.disabled || el.getAttribute('aria-hidden') === 'true') return false;
    return true;
  }
  function onTop(el, r) {
    // l'elemento è davvero visibile (non coperto da un banner/overlay)?
    const x = Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 2);
    const y = Math.min(Math.max(r.top + r.height / 2, 1), innerHeight - 2);
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return true;
    const hit = document.elementFromPoint(x, y);
    return !hit || hit === el || el.contains(hit) || hit.contains(el) || hit.id === '__nav_ring';
  }
  // Oltre ai link/pulsanti "veri", molti siti rendono cliccabili dei semplici riquadri via
  // JavaScript: si riconoscono perché il sito mostra la manina del mouse (cursor:pointer).
  // Il cursore si eredita, quindi si prende solo l'elemento più esterno con la manina.
  // Si "tasta" lo schermo con una griglia di punti: sotto ogni punto si risale fino al primo
  // elemento con la manina che non la eredita dal padre. Costo fisso, qualunque sia la pagina.
  const STEP = 44;
  function pointerRoots() {
    const out = new Set(), memo = new Map();
    const isPtr = el => {
      if (!el || el === document.body || el === document.documentElement) return false;
      let v = memo.get(el);
      if (v === undefined) { v = getComputedStyle(el).cursor === 'pointer'; memo.set(el, v); }
      return v;
    };
    for (let y = STEP / 2; y < innerHeight; y += STEP) {
      for (let x = STEP / 2; x < innerWidth; x += STEP) {
        let el = document.elementFromPoint(x, y);
        if (!el || el.id === '__nav_ring') continue;
        if (el.closest(SEL)) continue;                      // già coperto dai link/pulsanti
        if (!isPtr(el)) continue;
        while (isPtr(el.parentElement)) el = el.parentElement;
        out.add(el);
      }
    }
    return [...out];
  }
  // ---------- elenco dei cliccabili, calcolato in anticipo ----------
  // Calcolarlo costa (su pagine grandi anche 0,3 s), quindi si prepara mentre non si
  // premono tasti: dopo ogni spostamento, scroll o cambiamento della pagina. Al tasto
  // si ricalcolano solo le posizioni, che costano poco.
  let cache = null, building = 0, lastUse = 0, lastBuild = 0;
  function rebuild() {
    building = 0;
    const els = [];
    const seen = new Set();
    const add = el => {
      if (el.id === '__osk_host' || el.id === '__nav_ring' || seen.has(el)) return;
      seen.add(el); els.push(el);
    };
    const lim = innerHeight * 2.5;
    document.querySelectorAll(SEL).forEach(el => {
      const r = el.getBoundingClientRect();
      if (r.bottom < -lim || r.top > lim + innerHeight || r.width < 6 || r.height < 6) return;
      add(el);
    });
    pointerRoots().forEach(add);
    // tengo il più esterno quando un cliccabile ne contiene un altro
    cache = els.filter(el => { for (let p = el.parentElement; p; p = p.parentElement) if (seen.has(p)) return false; return true; });
    lastBuild = Date.now();
  }
  function schedule(delay) {
    if (building || Date.now() - lastUse > 60000) return;   // solo se si sta usando il telecomando
    building = setTimeout(rebuild, delay == null ? 300 : delay);
  }
  const watch = () => new MutationObserver(() => { if (Date.now() - lastBuild > 1200) schedule(400); })
    .observe(document.documentElement, { childList: true, subtree: true });
  if (document.documentElement) watch(); else document.addEventListener('DOMContentLoaded', watch);
  let scrollT = 0;
  window.addEventListener('scroll', () => { clearTimeout(scrollT); scrollT = setTimeout(() => schedule(0), 250); }, true);

  function candidates() {
    lastUse = Date.now();
    if (!cache) rebuild();
    const big = innerWidth * innerHeight * 0.5;
    const out = [];
    for (const el of cache) {
      if (!el.isConnected) continue;
      const r = el.getBoundingClientRect();
      if (r.width * r.height > big || !visible(el, r)) continue;
      out.push({ el, r });
    }
    return out;
  }
  // il migliore che sia davvero visibile (non coperto da un banner): si controlla solo lui
  function pickVisible(dir, list, from) {
    for (let i = 0; i < 6; i++) {
      const b = pick(dir, list, from);
      if (!b || onTop(b.el, b.r)) return b;
      list = list.filter(c => c !== b);
    }
    return null;
  }

  // ---------- movimento ----------
  function scrollBy(dir) {
    const dy = { up: -0.6, down: 0.6 }[dir], dx = { left: -0.6, right: 0.6 }[dir];
    const before = [scrollX, scrollY];
    window.scrollBy({ top: (dy || 0) * innerHeight, left: (dx || 0) * innerWidth, behavior: 'smooth' });
    return before;
  }
  function inView(r) { return r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth; }

  function pick(dir, list, from) {
    const ax = from.left + from.width / 2, ay = from.top + from.height / 2;
    let best = null, bd = Infinity;
    for (const c of list) {
      if (c.el === cur) continue;
      const b = c.r, bx = b.left + b.width / 2, by = b.top + b.height / 2;
      let main, cross, overlap;
      if (dir === 'left' || dir === 'right') {
        main = dir === 'left' ? from.left - b.right : b.left - from.right;
        if ((dir === 'left' ? ax - bx : bx - ax) < 4) continue;
        overlap = Math.min(from.bottom, b.bottom) - Math.max(from.top, b.top);
        cross = overlap > 0 ? 0 : Math.abs(by - ay);
      } else {
        main = dir === 'up' ? from.top - b.bottom : b.top - from.bottom;
        if ((dir === 'up' ? ay - by : by - ay) < 4) continue;
        overlap = Math.min(from.right, b.right) - Math.max(from.left, b.left);
        cross = overlap > 0 ? 0 : Math.abs(bx - ax);
      }
      const d = Math.max(main, -20) + cross * 2.5;
      if (d < bd) { bd = d; best = c; }
    }
    return best;
  }

  function focusEl(el) {
    cur = el;
    ensureRing();
    const r = el.getBoundingClientRect();
    if (r.top < 60 || r.bottom > innerHeight - 60 || r.left < 0 || r.right > innerWidth)
      el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
    try { el.focus({ preventScroll: true }); } catch (e) {}
    try { el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true })); } catch (e) {}
    place();
    clearInterval(raf); let n = 0;
    raf = setInterval(() => { place(); if (++n > 12) clearInterval(raf); }, 60);  // segue lo scroll
  }

  function move(dir) {
    if (window.__osk && __osk.isOpen()) {
      __osk.key({ up: 'ArrowUp', down: 'ArrowDown', left: 'ArrowLeft', right: 'ArrowRight' }[dir]);
      return 'osk';
    }
    const list = candidates();
    if (!cur || !cur.isConnected || !inView(cur.getBoundingClientRect())) {
      // primo tasto (o elemento sparito): il cliccabile visibile più in alto a sinistra
      const vis = list.filter(c => inView(c.r) && onTop(c.el, c.r)).sort((a, b) => (a.r.top - b.r.top) || (a.r.left - b.r.left));
      if (vis.length) { focusEl(vis[0].el); return 'first'; }
      scrollBy(dir); return 'scroll';
    }
    const from = cur.getBoundingClientRect();
    // prima tra quelli visibili, poi in tutta la pagina (vicini)
    let best = pickVisible(dir, list.filter(c => inView(c.r)), from);
    if (!best) {
      const near = pickVisible(dir, list, from);
      if (near) {
        const b = near.r, far = (dir === 'down' ? b.top - from.bottom : dir === 'up' ? from.top - b.bottom : 0);
        if (far < innerHeight * 0.9) best = near;
      }
    }
    if (best) { focusEl(best.el); schedule(); return 'moved'; }
    scrollBy(dir);
    return 'scroll';
  }

  // ---------- OK ----------
  function isText(el) {
    if (!el) return false;
    if (el.isContentEditable) return true;
    if (el.tagName === 'TEXTAREA') return true;
    return el.tagName === 'INPUT' && TEXT_TYPES.test(el.type || '');
  }
  function setValue(el, v) {
    el.focus();
    if (el.isContentEditable) { el.textContent = v; }
    else {
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  function submit(el) {
    const o = { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true };
    const go = el.dispatchEvent(new KeyboardEvent('keydown', o));
    el.dispatchEvent(new KeyboardEvent('keypress', o));
    el.dispatchEvent(new KeyboardEvent('keyup', o));
    if (go && el.form) { try { el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit(); } catch (e) {} }
  }
  function activate() {
    if (window.__osk && __osk.isOpen()) { __osk.key('Enter'); return 'osk'; }
    if (!cur || !cur.isConnected) return null;
    if (isText(cur)) {
      const el = cur;
      const label = el.getAttribute('aria-label') || el.placeholder || el.name || 'Scrivi';
      __osk.open({ title: label, value: el.isContentEditable ? el.textContent : el.value,
        secret: el.type === 'password',
        onDone: v => { setValue(el, v); if (el.tagName !== 'TEXTAREA') submit(el); place(); },
        onCancel: () => place() });
      return 'osk';
    }
    // clic "vero" fatto da tvd tramite Chrome nel centro dell'elemento
    const r = cur.getBoundingClientRect();
    return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + Math.min(r.height / 2, 40)) };
  }
  function back() {
    if (window.__osk && __osk.isOpen()) { __osk.cancel(); return true; }
    return false;
  }

  // niente barre di scorrimento (sulla TV non servono: si scorre con le frecce)
  function noScrollbars() {
    const st = document.createElement('style');
    st.id = '__nav_noscroll';
    st.textContent = '*{scrollbar-width:none!important}' +
                     '::-webkit-scrollbar{display:none!important;width:0!important;height:0!important}';
    (document.head || document.documentElement).appendChild(st);
  }
  // nel primo istante la pagina non ha ancora la radice: appena nasce (non a pagina finita,
  // altrimenti la barra si vede per un attimo)
  if (document.documentElement) noScrollbars();
  else {
    const mo = new MutationObserver(() => { if (document.documentElement) { mo.disconnect(); noScrollbars(); } });
    mo.observe(document, { childList: true });
  }

  window.__nav = { move, activate, back, hide, current: () => cur };
})();

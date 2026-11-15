// core.js — pezzi comuni del launcher: dialogo con tvd, stato, finestre, frecce.

// ---------- dialogo con tvd (API su 127.0.0.1) ----------
export async function api(path) {
  try {
    const r = await fetch('/api/' + path, { cache: 'no-store' });
    return await r.json();
  } catch (e) { return null; }
}
export const q = encodeURIComponent;

// preferenze piccole del solo launcher (salvaschermo, ultimo riquadro): nel browser della TV
export const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
};

// ---------- stato condiviso ----------
export const state = {
  CFG: null,           // risposta di /api/config
  ONAIR: {},           // programmi in onda
  page: 'home',
  busy: false,         // un'operazione in corso: MENU non chiude la finestra
  asleep: false,       // schermo spento da tvd (timer): niente salvaschermo finché non si sveglia
  show: null,          // impostata da app.js: show(pagina)
};
export const $ = sel => document.querySelector(sel);

export function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

// voce di elenco (impostazioni, Wi-Fi, siti): testo, riga sotto e azione per OK
export function item(label, sub, fn) {
  const b = el('div', 'btn', label);
  b.tabIndex = 0;
  if (sub) b.appendChild(el('span', 'sub', sub));
  b._act = fn;
  return b;
}

export function focusAct(a) {
  const e = document.querySelector(`[data-act="${a}"]`);
  if (e) e.focus();
}

// ---------- finestre: messaggio, attesa (senza pulsanti) o scelta ----------
// buttons: [[testo, azione], ...]; l'ultimo è il predefinito (di solito "Annulla")
let returnTo = null;                     // la voce da cui si è aperta la finestra
export function overlay(msg, buttons, focus) {
  if (!overlayOpen()) returnTo = document.activeElement;
  $('#omsg').textContent = msg;
  $('#spin').style.display = buttons ? 'none' : 'block';
  const row = $('#obtns');
  row.innerHTML = '';
  row.classList.toggle('col', (buttons || []).length > 4);    // tante scelte: in colonna
  (buttons || []).forEach(([label, fn]) => {
    const b = el('div', 'btn', label);
    b.tabIndex = 0;
    b._act = fn;
    row.appendChild(b);
  });
  $('#overlay').classList.add('show');
  if (!buttons) return;
  const bs = row.querySelectorAll('.btn');
  const f = typeof focus === 'number' ? bs[focus]
    : [...bs].find(b => b.textContent.includes('✓')) || bs[bs.length - 1];
  (f || bs[bs.length - 1]).focus();
}
export const overlayOpen = () => $('#overlay').classList.contains('show');
export function hideOverlay() {
  $('#overlay').classList.remove('show');
  state.show(state.page);
  // si torna sulla voce di partenza (non sulla prima della pagina)
  if (returnTo && returnTo.isConnected && $('#page-' + state.page).contains(returnTo)) returnTo.focus();
  returnTo = null;
}
// scelta da un elenco con il segno ✓ sulla voce attuale
export function choose(title, options, current) {
  overlay(title, options.map(([label, value, fn]) =>
    [label + (value === current ? '  ✓' : ''), fn]).concat([['Annulla', hideOverlay]]));
}

// ---------- frecce: l'elemento più vicino nella direzione premuta ----------
function focusables() {
  const root = overlayOpen() ? $('#overlay') : $('#page-' + state.page);
  return [...root.querySelectorAll('[tabindex]')];
}

export function move(dir) {
  const items = focusables();
  if (!items.length) return;
  const cur = document.activeElement;
  if (!items.includes(cur)) { items[0].focus(); return; }
  // fila dei canali: gira in cerchio (dal primo con ◄ all'ultimo e viceversa)
  const sc = cur.closest('.row.scroller');
  if (sc && (dir === 'left' || dir === 'right')) {
    const row = [...sc.querySelectorAll('[tabindex]')];
    const i = row.indexOf(cur), n = row.length;
    if (n > 1 && ((dir === 'left' && i === 0) || (dir === 'right' && i === n - 1))) {
      row[dir === 'left' ? n - 1 : 0].focus();          // la fila si centra da sola (centerInRow)
      return;
    }
  }
  const a = cur.getBoundingClientRect(), ax = a.left + a.width / 2, ay = a.top + a.height / 2;
  let best = null, bd = Infinity;
  for (const e of items) {
    if (e === cur) continue;
    const b = e.getBoundingClientRect(), dx = b.left + b.width / 2 - ax, dy = b.top + b.height / 2 - ay;
    let main, cross;
    if (dir === 'left') { if (dx > -5) continue; main = -dx; cross = Math.abs(dy); }
    if (dir === 'right') { if (dx < 5) continue; main = dx; cross = Math.abs(dy); }
    if (dir === 'up') { if (dy > -5) continue; main = -dy; cross = Math.abs(dx); }
    if (dir === 'down') { if (dy < 5) continue; main = dy; cross = Math.abs(dx); }
    const d = main + cross * 2.2;
    if (d < bd) { bd = d; best = e; }
  }
  if (!best) return;
  best.focus();
  if (!best.closest('.row.scroller')) best.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

// fila dei canali: la scheda scelta resta al centro e scorre la fila (come nel pannello)
export function centerInRow(e) {
  const row = e.closest && e.closest('.row.scroller');
  if (!row) return;
  const max = row.scrollWidth - row.clientWidth;
  const left = Math.max(0, Math.min(max, e.offsetLeft - row.clientWidth / 2 + e.offsetWidth / 2));
  row.scrollTo({ left, behavior: 'smooth' });
}

// ---------- piccole utilità grafiche ----------
export function shade(hex) {            // colore più scuro per le sfumature dei riquadri
  const n = parseInt(hex.slice(1), 16);
  const f = c => Math.max(0, Math.round(c * 0.55)).toString(16).padStart(2, '0');
  return '#' + f(n >> 16) + f((n >> 8) & 255) + f(n & 255);
}
export function hasTransparency(img) {   // il logo ha il fondo trasparente? (i quattro angoli)
  try {
    const c = document.createElement('canvas'), w = img.naturalWidth, h = img.naturalHeight;
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    g.drawImage(img, 0, 0);
    return [[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]].some(([x, y]) => g.getImageData(x, y, 1, 1).data[3] < 128);
  } catch (e) { return false; }
}
export function edgeFade(row) {          // sfumatura ai bordi, solo dal lato dove c'è altro
  const l = row.scrollLeft > 2, r = row.scrollLeft + row.clientWidth < row.scrollWidth - 2;
  const g = (l || r) ? `linear-gradient(90deg, ${l ? 'transparent 0, #000 6vw' : '#000 0'}, ` +
    `${r ? '#000 calc(100% - 6vw), transparent 100%' : '#000 100%'})` : '';
  row.style.webkitMaskImage = g;
  row.style.maskImage = g;
}

// guide.js — Guida TV: a sinistra i canali, a destra i loro programmi delle prossime ore.
// Scegliendo un canale (frecce su/giù) si caricano i suoi programmi; → per scorrerli;
// OK sul programma in onda (o sul canale) apre la diretta.
import { $, api, el, hideOverlay, overlay, q, state } from './core.js';

const cache = {};                 // id canale -> {t, programs}
let shown = null, loadTimer = 0;

function openChannel(id) {
  if (state.busy) return;
  state.busy = true;
  overlay('Apertura di ' + state.CFG.services[id].label + '…');
  api('open?id=' + q(id));
  setTimeout(() => { state.busy = false; }, 8000);
}

function row(p, id, now) {
  const live = p.start <= now && now < p.end;
  const r = el('div', 'gprog' + (live ? ' live' : ''));
  r.tabIndex = 0;
  const t = el('div', 'gtime', window.TVCards.hhmm(p.start));
  if (live) t.appendChild(el('span', 'gnow', 'IN ONDA'));
  const body = el('div', 'gbody');
  body.appendChild(el('div', 'gtitle', p.title));
  if (p.desc) body.appendChild(el('div', 'gdesc', p.desc));
  if (live) {
    const bar = el('div', 'bar'), i = el('i');
    i.style.width = window.TVCards.progress(p, now) + '%';
    bar.appendChild(i);
    body.appendChild(bar);
  }
  r.append(t, body);
  if (p.image) { const im = el('div', 'gpic'); im.style.backgroundImage = `url("${p.image}")`; r.appendChild(im); }
  r._act = live ? () => openChannel(id)
    : () => overlay(`${p.title}\ninizia alle ${window.TVCards.hhmm(p.start)}`, [['Guarda il canale ora', () => openChannel(id)], ['OK', hideOverlay]]);
  return r;
}

async function showPrograms(id) {
  if (shown === id) return;
  shown = id;
  const list = $('#guide-progs');
  const c = cache[id];
  if (!c || Date.now() - c.t > 5 * 60000) {
    list.innerHTML = '';
    list.appendChild(el('div', 'gwait', 'Carico la guida…'));
    const r = await api('guide?id=' + q(id));
    cache[id] = { t: Date.now(), programs: (r && r.programs) || [] };
  }
  if (shown !== id) return;                // nel frattempo si è passati a un altro canale
  list.innerHTML = '';
  const now = Date.now(), progs = cache[id].programs;
  if (!progs.length) list.appendChild(el('div', 'gwait', 'Guida non disponibile per questo canale'));
  progs.forEach(p => list.appendChild(row(p, id, now)));
  list.scrollTop = 0;
}

export async function guidePage() {
  const chans = $('#guide-chans');
  chans.innerHTML = '';
  shown = null;
  const r = await api('guide');
  ((r && r.channels) || []).forEach(c => {
    const b = el('div', 'btn gch', c.label);
    b.tabIndex = 0;
    b.dataset.gid = c.id;
    b.style.setProperty('--ch', c.color || '#334155');
    b._act = () => openChannel(c.id);
    chans.appendChild(b);
  });
  const last = state.CFG && document.querySelector(`#guide-chans [data-gid="${state.guideFrom || ''}"]`);
  (last || chans.querySelector('[tabindex]')).focus();
}

// scegliendo un canale a sinistra si caricano i suoi programmi (con un attimo di attesa:
// scorrendo veloce non si scaricano tutte le guide)
document.addEventListener('focusin', ev => {
  const b = ev.target.closest && ev.target.closest('#guide-chans .gch');
  if (!b) return;
  document.querySelectorAll('#guide-chans .gch.sel').forEach(e => e.classList.remove('sel'));
  b.classList.add('sel');
  clearTimeout(loadTimer);
  loadTimer = setTimeout(() => showPrograms(b.dataset.gid), 250);
});

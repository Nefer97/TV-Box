// saver.js — salvaschermo: le foto dei programmi in onda con movimento lento, orologio e meteo.
// Parte dopo N minuti senza tasti, solo nella home; il primo tasto lo spegne soltanto.
import { $, choose, focusAct, hideOverlay, overlayOpen, state, store } from './core.js';

let lastInput = Date.now(), idx = -1, layer = 0, timer = 0;

export function saverMin() {               // 0 = mai; scelta salvata nel browser della TV
  const v = parseInt(store.get('saver-min'), 10);
  return isNaN(v) ? 5 : v;
}
export function saverLabel() { const m = saverMin(); return m ? `dopo ${m} minuti` : 'mai'; }

function setMin(m) {
  store.set('saver-min', m);
  hideOverlay();
  $('#saver-val').textContent = saverLabel();
  focusAct('saver');
}
export function saverMenu() {
  choose('Salvaschermo', [['Prova ora', 'test', () => { hideOverlay(); setTimeout(saverStart, 300); }]]
    .concat([2, 5, 10, 30].map(m => [`Dopo ${m} minuti`, m, () => setMin(m)]), [['Mai', 0, () => setMin(0)]]),
    saverMin());
}

const on = () => $('#saver').classList.contains('show');

function slides() {                        // i canali della home con una foto del programma
  return [...document.querySelectorAll('.tvcard[data-onair]')]
    .map(c => ({ ch: state.CFG.services[c.dataset.id].label, d: state.ONAIR[c.dataset.onair] }))
    .filter(x => x.d && x.d.image_big);
}
function text() {
  $('#saver .sclock').textContent = new Date().toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
  $('#saver .sdate').textContent = $('#datetext').textContent;
  const m = $('#meteo .t'), ic = $('#meteo .ic');
  $('#saver .smeteo').textContent = m ? `${ic ? ic.textContent : ''} ${m.textContent}` : '';
}
function next() {                          // foto successiva, con dissolvenza
  const sv = $('#saver'), all = slides();
  sv.classList.toggle('flip');             // orologio e didascalia cambiano lato
  text();
  if (!all.length) return;
  idx = (idx + 1) % all.length;
  const x = all[idx], layers = sv.querySelectorAll('.sbg');
  const nxt = layers[layer ^ 1], prev = layers[layer];
  const img = new Image();
  img.onload = () => {                     // cambia solo quando la foto è pronta
    nxt.style.backgroundImage = `url("${x.d.image_big}")`;
    nxt.classList.remove('kb1', 'kb2', 'kb3');
    void nxt.offsetWidth;                  // riparte l'animazione
    nxt.classList.add('kb' + (1 + Math.floor(Math.random() * 3)), 'on');
    prev.classList.remove('on');
    layer ^= 1;
    setTimeout(() => { if (!prev.classList.contains('on')) prev.classList.remove('kb1', 'kb2', 'kb3'); }, 1600);
    sv.querySelector('.sch').textContent = 'Ora su ' + x.ch;
    sv.querySelector('.stitle').textContent = x.d.title;
  };
  img.src = x.d.image_big;
}
export function saverStart() {
  $('#saver').classList.add('show');
  next();
  clearInterval(timer);
  timer = setInterval(next, 25000);
}
export function saverStop() {
  $('#saver').classList.remove('show');
  clearInterval(timer);
}

export function initSaver() {
  setInterval(() => {
    if (!on() && state.page === 'home' && !overlayOpen() && !(window.__osk && window.__osk.isOpen())
        && saverMin() > 0 && Date.now() - lastInput > saverMin() * 60000) saverStart();
    else if (on()) text();
  }, 30000);
  window.addEventListener('keydown', ev => {
    lastInput = Date.now();
    if (on()) { saverStop(); ev.preventDefault(); ev.stopImmediatePropagation(); }   // sveglia soltanto
  }, true);
  window.addEventListener('mousemove', () => { lastInput = Date.now(); if (on()) saverStop(); }, true);
  window.addEventListener('pageshow', () => { lastInput = Date.now(); saverStop(); });
}

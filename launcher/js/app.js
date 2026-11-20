// app.js — avvio del launcher: pagine, tasti, aggiornamenti periodici.
import { $, api, centerInRow, fadesAround, hideOverlay, move, overlay, overlayOpen, state, store } from './core.js';
import { build, greeting, showDetail, tick, updateMeteo, updateOnAir, updateStatus } from './home.js';
import { guidePage } from './guide.js';
import { msPage, seriesPage } from './mediaset.js';
import { scPage, scSeriesPage } from './sc.js';
import { auPage, auSeriesPage } from './au.js';
import { channelsPage, homeEditPage, sitiPage, sitoApri, wifiPage } from './lists.js';
import { initSaver, saverAwake } from './saver.js';
import { ACTIONS, changeVolume, loginPage, settingsPage } from './settings.js';

const TITLES = { altri: 'Altri servizi', settings: 'Impostazioni', wifi: 'Wi-Fi', siti: 'I miei siti',
  homeedit: 'Riquadri della home', guide: 'Guida TV', channels: 'Canali in diretta', mediaset: 'Mediaset Infinity', msserie: 'Mediaset Infinity', sc: 'StreamingCommunity', scserie: 'StreamingCommunity', au: 'AnimeUnity', auserie: 'AnimeUnity', 'set-av': 'Immagine e audio',
  'set-power': 'Accensione e spegnimento', 'set-home': 'Home e contenuti', 'set-net': 'Rete e assistenza', login: 'Accesso' };
// MENU: pagina a cui si torna (e voce da selezionare)
const PARENT = { wifi: ['set-net', 'wifi'], homeedit: ['set-home', 'home-edit'], channels: ['set-home', 'channels'], siti: ['altri'],
  settings: ['home'], altri: ['home'], guide: ['home'], mediaset: ['home'], msserie: ['mediaset'], sc: ['altri'], scserie: ['sc'], au: ['altri'], auserie: ['au'],
  'set-av': ['settings', 'set-av'], 'set-power': ['settings', 'set-power'],
  'set-home': ['settings', 'set-home'], 'set-net': ['settings', 'set-net'], login: ['set-net'] };
// cosa preparare entrando in una pagina
const ON_ENTER = { settings: settingsPage, 'set-av': settingsPage, 'set-power': settingsPage,
  'set-home': settingsPage, 'set-net': settingsPage, login: loginPage,
  wifi: wifiPage, siti: sitiPage, homeedit: () => homeEditPage(), guide: guidePage,
  mediaset: msPage, msserie: seriesPage, sc: scPage, scserie: scSeriesPage, au: auPage, auserie: auSeriesPage, channels: () => channelsPage() };

// sezioni con un riquadro che può stare in home o in Altri servizi: MENU torna dove era il
// riquadro da cui si è entrati (ricordato nel browser: vale anche dopo un episodio, quando il
// launcher si ricarica da capo)
const SECTIONS = ['mediaset', 'sc', 'au'];

function show(p) {
  const prev = state.page;
  if (SECTIONS.includes(p) && (prev === 'home' || prev === 'altri')) store.set('from-' + p, prev);
  state.page = p;
  document.body.dataset.page = p;
  document.querySelectorAll('.page').forEach(s => s.classList.toggle('active', s.id === 'page-' + p));
  $('#title').textContent = p === 'home' ? greeting() : TITLES[p] || '';
  const last = p === 'home' && store.get('last-tile');
  const target = (last && document.querySelector(`#page-home [data-id="${last}"]`))
    || document.querySelector(`#page-${p} [tabindex]`);
  if (target) target.focus();
  setTimeout(() => showDetail(document.activeElement), 0);
  // impostazioni: si aggiornano ogni volta; le liste solo arrivando da un'altra pagina
  if (ON_ENTER[p] && (p === 'settings' || p.startsWith('set-') || p === 'msserie' || p === 'scserie' || p === 'auserie' || prev !== p)) ON_ENTER[p]();
}
state.show = show;

function back() {
  if (overlayOpen()) { if (!state.busy) hideOverlay(); return; }
  const p = state.page, from = SECTIONS.includes(p) && store.get('from-' + p);
  const to = from === 'home' || from === 'altri' ? [from] : PARENT[p];
  if (!to) return;
  show(to[0]);
  if (to[0] === 'altri') {                 // sul riquadro della sezione appena lasciata
    const id = Object.keys(state.CFG.services).find(k => state.CFG.services[k].page === p);
    const e = id && document.querySelector(`#altri-row [data-id="${id}"]`);
    if (e) e.focus();
  }
  if (to[1]) {
    const e = document.querySelector(`#page-${to[0]} [data-act="${to[1]}"], #page-${to[0]} [data-go="${to[1]}"]`);
    if (e) e.focus();
  }
}

function activate(e) {
  if (!e) return;
  if (e._act) return e._act();
  if (e.dataset.go) return show(e.dataset.go);                    // gruppo delle Impostazioni
  if (e.dataset.url) return sitoApri(e.dataset.url);
  if (e.dataset.id) {
    const s = state.CFG.services[e.dataset.id];
    if (state.page === 'home') store.set('last-tile', e.dataset.id);
    if (s.page) return show(s.page);
    if (state.busy) return;
    state.busy = true;
    overlay('Apertura di ' + s.label + '…');
    api('open?id=' + encodeURIComponent(e.dataset.id));
    setTimeout(() => { state.busy = false; }, 8000);
    return;
  }
  const fn = ACTIONS[e.dataset.act];
  if (fn) fn();
}

const ARROWS = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right' };
document.addEventListener('keydown', ev => {
  const k = ev.key, a = document.activeElement;
  // volume: ◀ ▶ sulla voce Volume
  if (a && a.classList.contains('volctl') && (k === 'ArrowLeft' || k === 'ArrowRight') && !overlayOpen()) {
    changeVolume(k === 'ArrowRight' ? 5 : -5);
  } else if (ARROWS[k]) move(ARROWS[k]);
  else if (k === 'Enter' || k === ' ') activate(a);
  else if (k === 'Escape' || k === 'Backspace') back();
  else return;
  ev.preventDefault();
});
document.addEventListener('click', ev => {
  const e = ev.target.closest('[tabindex]');
  if (e) { e.focus(); activate(e); }
});
document.addEventListener('focusin', ev => {
  showDetail(ev.target); centerInRow(ev.target);
  fadesAround(ev.target); setTimeout(() => fadesAround(ev.target), 450);   // e a scorrimento finito
});
document.addEventListener('scroll', ev => fadesAround(ev.target), true);     // righe e liste che scorrono
document.addEventListener('mousemove', () => {
  document.body.classList.add('pointer');
  clearTimeout(window._pt);
  window._pt = setTimeout(() => document.body.classList.remove('pointer'), 3000);
});
// tornando alla pagina dalla cronologia: via la finestra "Apertura…"
window.addEventListener('pageshow', () => { state.busy = false; $('#overlay').classList.remove('show'); });

(async function init() {
  tick();
  setInterval(tick, 10000);
  initSaver();
  for (let i = 0; i < 20 && !state.CFG; i++) {
    state.CFG = await api('config');
    if (!state.CFG) await new Promise(r => setTimeout(r, 500));
  }
  if (!state.CFG) { $('#title').textContent = 'Errore: servizio TV non attivo'; return; }
  build();
  const start = location.hash.slice(1);                           // tvd può aprire Impostazioni o Guida
  state.asleep = start === 'sleep';                                // ...o la home a schermo spento
  window.__tvWake = saverAwake;
  // tvd: MENU tenuto premuto nel launcher. Dalla home le Impostazioni, altrove la home
  window.__tvMenuLong = () => {
    if (window.__osk && __osk.isOpen()) __osk.cancel();
    if (overlayOpen()) hideOverlay();
    show(state.page === 'home' ? 'settings' : 'home');
    return true;
  };                                    // tvd: schermo riacceso
  if (start.startsWith('ms:')) { state.msSeries = start.slice(3); show('msserie'); }     // MENU da un episodio
  else if (start.startsWith('sc:')) { state.scSeries = start.slice(3); show('scserie'); }
  else if (start.startsWith('au:')) { state.auSeries = start.slice(3); show('auserie'); }
  else show(['settings', 'guide', 'mediaset', 'sc', 'au'].includes(start) ? start : 'home');
  if (location.hash) history.replaceState(null, '', location.pathname);
  updateOnAir(); setInterval(updateOnAir, 60000);
  updateStatus(); setInterval(updateStatus, 30000);
  updateMeteo(); setInterval(updateMeteo, 10 * 60000);
})();

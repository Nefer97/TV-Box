// settings.js — pagina Impostazioni: volume, meteo, risoluzione, rete, riavvio/spegnimento.
import { $, api, choose, focusAct, hideOverlay, overlay, q, state } from './core.js';
import { updateMeteo } from './home.js';
import { saverLabel, saverMenu } from './saver.js';

// ---------- volume (◀ ▶ sulla voce Volume) ----------
export function setVol(r) {
  if (!r || r.volume == null) return;
  document.querySelectorAll('.vol').forEach(e => { e.textContent = r.volume + '%'; });
  document.querySelectorAll('.volbar i').forEach(e => { e.style.width = r.volume + '%'; });
}
export const changeVolume = delta => api('volume?delta=' + delta).then(setVol);

// ---------- rete ----------
function refreshInfo() {
  api('info').then(r => { $('#ip').textContent = r && r.ip && r.ip.length ? r.ip[0] : 'non connesso'; });
  api('wifi').then(w => {
    $('#wifi-cur').textContent = !w || !w.present ? 'assente' : w.connected ? w.ssid : 'non collegato';
  });
}

// ---------- account (Mediaset, StreamingCommunity): chi è collegato; OK per uscire ----------
// una riga per servizio (data-svc = id del servizio = indirizzo /api/<id>); l'accesso si fa
// aprendo la sezione, che senza account mostra la schermata di accesso (login.js)
async function accountVal(row) {
  const id = row.dataset.svc, s = state.CFG.services[id];
  row.style.display = s ? '' : 'none';
  if (!s) return null;
  row.querySelector('.aname').textContent = s.label;
  const l = await api(id + '?action=status');
  row.querySelector('.val').textContent = !l ? '…' : l.logged ? (l.user || 'collegato') : 'non collegato';
  return l;
}
const accountRows = () => document.querySelectorAll('[data-act="account"]');
async function account() {
  const row = document.activeElement.closest('[data-act="account"]');
  if (!row) return;
  const id = row.dataset.svc, name = state.CFG.services[id].label;
  const l = await accountVal(row);
  if (!l || !l.logged) {
    overlay(`Non sei collegato a ${name}.\nL'accesso si fa aprendo la sezione.`, [['OK', hideOverlay]]);
    return;
  }
  overlay(`Uscire dall'account ${name}${l.user ? ' «' + l.user + '»' : ''}?`, [
    ['Esci', async () => {
      overlay('Esco…');
      await api(id + '?action=logout');
      hideOverlay();
      accountVal(row);
    }],
    ['Annulla', hideOverlay]], 1);
}

// ---------- meteo: città scelta con la tastiera a schermo ----------
function meteoCitta() {
  window.__osk.open({
    title: 'Città per il meteo (es. Roma)',
    onDone: async v => {
      if (!v.trim()) { state.show('set-home'); return; }
      overlay('Cerco ' + v + '…');
      const r = await api('meteo?action=search&q=' + q(v));
      const res = (r && r.results) || [];
      if (!res.length) { overlay('Nessuna città trovata', [['OK', hideOverlay]]); return; }
      overlay('Quale città?', res.map(c => [`${c.name} (${c.area})`, async () => {
        await api(`meteo?action=set&name=${q(c.name)}&lat=${c.lat}&lon=${c.lon}`);
        hideOverlay(); updateMeteo(); focusAct('meteo');
      }]).concat([['Annulla', hideOverlay]]), 0);
    },
    onCancel: () => { state.show('set-home'); focusAct('meteo'); },
  });
}

// ---------- risoluzione: prova di 15 s, se non si conferma torna quella di prima ----------
export function resName(m) {
  const [w, h] = m.split('x').map(Number);
  const tag = h === 720 && w === 1280 ? 'HD' : h === 1080 ? 'Full HD' : h === 768 && w >= 1360 ? 'HD Ready'
    : h === 2160 ? '4K' : Math.abs(w / h - 4 / 3) < 0.02 ? '4:3' : '';
  return `${w} × ${h}` + (tag ? ` (${tag})` : '');
}
async function screenVal() {
  const r = await api('screen');
  $('#screen-val').textContent = r && r.current ? resName(r.current) : '…';
  $('#screenvideo-val').textContent = !r || !r.video_mode ? '—'
    : r.video_low ? `abbassa a ${resName(r.video_mode)}` : 'come il menu';
}
async function screenMenu() {
  const r = await api('screen');
  if (!r || !r.modes) { overlay('Schermo non trovato', [['OK', hideOverlay]]); return; }
  const modes = r.modes.filter(m => +m.split('x')[0] >= 1024).slice(0, 7);
  choose('Risoluzione schermo',
    [[`Automatica (${r.preferred ? resName(r.preferred) : '—'})`, 'auto', () => screenTry('auto', 'automatica')]]
      .concat(modes.map(m => [resName(m), m, () => screenTry(m, resName(m))])),
    r.saved);
}
async function screenTry(mode, name) {
  const r = await api('screen?action=try&mode=' + q(mode));
  if (!r || !r.ok) { overlay((r && r.error) || 'Non riuscito', [['OK', hideOverlay]]); return; }
  let left = r.seconds || 15;
  const msg = () => `Si vede bene e a tutto schermo?\nSe non confermi, torno alla risoluzione di prima tra ${left} s`;
  const end = (text, wait) => {
    clearInterval(t);
    overlay(text);
    setTimeout(() => { hideOverlay(); focusAct('screen'); screenVal(); }, wait);
  };
  const done = keep => { api('screen?action=' + (keep ? 'keep' : 'revert'));
    end(keep ? `Risoluzione ${name} salvata` : 'Torno alla risoluzione di prima…', keep ? 2500 : 3000); };
  overlay(msg(), [['Sì, tienila', () => done(true)], ['No, torna indietro', () => done(false)]]);
  const t = setInterval(() => {
    if (--left <= 0) end('Torno alla risoluzione di prima…', 3000);   // tvd torna indietro da solo
    else $('#omsg').textContent = msg();
  }, 1000);
}
async function screenVideoMenu() {
  const r = await api('screen');
  if (!r || !r.video_mode) { overlay('Non disponibile', [['OK', hideOverlay]]); return; }
  const set = on => { api('screen?action=video&on=' + (on ? 1 : 0)); hideOverlay(); focusAct('screen-video');
    setTimeout(screenVal, 1500); };
  choose('Durante i video', [
    [`Abbassa a ${resName(r.video_mode)}: più fluido`, true, () => set(true)],
    ['Come il menu: niente cambi di schermo', false, () => set(false)]], r.video_low);
}

// ---------- all'accensione ----------
async function startupVal() {
  const r = await api('prefs');
  $('#startup-val').textContent = r && r.startup === 'home' ? 'la home' : 'l\'ultimo canale';
  return r;
}
async function startupMenu() {
  const r = await startupVal();
  const set = v => async () => { await api('prefs?key=startup&value=' + v); hideOverlay(); startupVal(); };
  choose('All\'accensione', [['Riparti dall\'ultimo canale guardato', 'last', set('last')],
    ['Mostra la home', 'home', set('home')]], r && r.startup);
}

// ---------- schermo spento dopo tanto salvaschermo ----------
const offLabel = m => (m ? `dopo ${m >= 60 ? m / 60 + (m === 60 ? ' ora' : ' ore') : m + ' minuti'} di salvaschermo` : 'mai');
async function saverOffVal() {
  const r = await api('prefs');
  $('#saveroff-val').textContent = offLabel(r ? r.saver_off : 60);
  return r;
}
async function saverOffMenu() {
  const r = await saverOffVal();
  const set = m => async () => { await api('prefs?key=saver_off&value=' + m); hideOverlay(); saverOffVal(); };
  choose('Spegni lo schermo dopo', [30, 60, 120].map(m => [offLabel(m), m, set(m)])
    .concat([['Mai', 0, set(0)]]), r && r.saver_off);
}

// ---------- timer di spegnimento ----------
async function sleepVal() {
  const r = await api('sleep');
  $('#sleep-val').textContent = r && r.minutes ? `tra ${r.minutes} minuti` : 'spento';
  return r;
}
async function sleepMenu() {
  await sleepVal();
  const set = m => async () => { await api('sleep?minutes=' + m); hideOverlay(); sleepVal(); };
  choose('Timer di spegnimento', [30, 60, 90, 120].map(m => [`Tra ${m} minuti`, m, set(m)])
    .concat([['Spento', 0, set(0)]]), -1);
}

// ---------- sistema ----------
function confirmAct(question, action, msg) {
  overlay(question, [['Sì', () => { overlay(msg); api('system?action=' + action); }], ['Annulla', hideOverlay]]);
}

// azioni delle voci (data-act nell'HTML)
export const ACTIONS = {
  meteo: meteoCitta,
  screen: screenMenu,
  'screen-video': screenVideoMenu,
  saver: saverMenu,
  startup: startupMenu,
  sleep: sleepMenu,
  'saver-off': saverOffMenu,
  info: refreshInfo,
  account,
  wifi: () => state.show('wifi'),
  'home-edit': () => state.show('homeedit'),
  channels: () => state.show('channels'),
  'restart-ui': () => { overlay('Ricarico l\'interfaccia…'); api('system?action=restart-ui'); },
  reboot: () => confirmAct('Riavviare il Mac mini?', 'reboot', 'Riavvio…'),
  poweroff: () => confirmAct('Spegnere il Mac mini?', 'poweroff', 'Spegnimento…'),
};

export async function settingsPage() {
  api('volume').then(setVol);
  refreshInfo();
  accountRows().forEach(accountVal);
  updateMeteo();
  screenVal();
  $('#saver-val').textContent = saverLabel();
  startupVal();
  sleepVal();
  saverOffVal();
  // riassunto sotto ogni gruppo
  const [v, sc, st, sl, w, m] = await Promise.all(['volume', 'screen', 'prefs', 'sleep', 'wifi', 'meteo'].map(api));
  $('#sum-av').textContent = [v && v.volume != null ? `Volume ${v.volume}%` : '',
    sc && sc.current ? resName(sc.current) : ''].filter(Boolean).join(' · ');
  $('#sum-power').textContent = (sl && sl.minutes ? `Timer ${sl.minutes} min` : 'Timer spento') + ' · ' +
    (st && st.startup === 'home' ? 'parte dalla home' : 'ultimo canale');
  $('#sum-home').textContent = m && m.city ? `Meteo: ${m.city}` : 'Scegli la città del meteo';
  $('#sum-net').textContent = !w || !w.present ? 'Wi-Fi assente' : w.connected ? `Wi-Fi: ${w.ssid}` : 'Wi-Fi non collegato';
}

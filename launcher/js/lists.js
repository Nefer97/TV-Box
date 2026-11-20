// lists.js — pagine a elenco: Wi-Fi, I miei siti, Schermata iniziale.
import { $, api, el, hideOverlay, item, overlay, q, state, store } from './core.js';
import { build, rebuild } from './home.js';

// ======================================================================== Wi-Fi
const bars = dbm => (dbm >= -55 ? 'ottimo' : dbm >= -67 ? 'buono' : dbm >= -75 ? 'discreto' : 'debole');

function wifiStatusText(w) {
  const box = $('#wifi-status');
  box.innerHTML = '';
  const line = (t, muted) => { const d = document.createElement('div'); d.textContent = t;
    if (muted) d.className = 'muted'; box.appendChild(d); };
  if (!w) return line('Servizio TV non raggiungibile', true);
  if (!w.present) return line('Nessuna scheda Wi-Fi trovata', true);
  if (w.error) return line(w.error, true);
  if (!w.connected) return line('Non collegato. Scegli una rete qui sotto.', true);
  line(`Collegato a «${w.ssid}»` + (w.signal != null ? ` · segnale ${bars(w.signal)}` : ''));
  line(w.ip ? 'Indirizzo ' + w.ip : 'In attesa dell\'indirizzo…', true);
}
export async function wifiPage() {
  const list = $('#wifi-list');
  list.innerHTML = '';
  list.appendChild(item('Cerca reti', 'Aggiorna l\'elenco delle reti vicine', wifiScan));
  wifiStatusText(await api('wifi'));
  wifiScan();
}
async function wifiScan() {
  overlay('Cerco le reti Wi-Fi…');
  const [st, sc] = await Promise.all([api('wifi'), api('wifi?action=scan')]);
  $('#overlay').classList.remove('show');
  wifiStatusText(st);
  const list = $('#wifi-list'), nets = (sc && sc.networks) || [];
  list.innerHTML = '';
  nets.forEach(n => {
    const cur = st && st.connected && st.ssid === n.ssid;
    const sub = [cur ? 'collegata' : n.saved ? 'salvata' : '', n.secure ? 'protetta' : 'aperta',
      'segnale ' + bars(n.signal)].filter(Boolean).join(' · ');
    list.appendChild(item(n.ssid, sub, () => wifiChoose(n, cur)));
  });
  list.appendChild(item('Cerca di nuovo', nets.length ? '' : 'Nessuna rete trovata', wifiScan));
  if (state.page === 'wifi') (list.querySelector('[tabindex]') || list).focus();
}
function wifiChoose(n, cur) {
  if (n.wep) return overlay('Le reti WEP non sono supportate', [['OK', hideOverlay]]);
  const askPw = () => window.__osk.open({
    title: `Password del Wi-Fi «${n.ssid}»`,
    onDone: pw => wifiConnect(n.ssid, pw),
    onCancel: () => state.show('wifi'),
  });
  if (cur) {
    overlay(`Sei già collegato a «${n.ssid}».`,
      [['Dimentica rete', () => wifiForget(n.ssid)], ['Cambia password', askPw], ['OK', hideOverlay]]);
  } else if (n.saved) {
    overlay(`Collegarsi a «${n.ssid}»?`, [['Dimentica rete', () => wifiForget(n.ssid)], ['Cambia password', askPw],
      ['Collegati', () => wifiConnect(n.ssid, '')], ['Annulla', hideOverlay]], 2);
  } else if (n.secure) askPw();
  else wifiConnect(n.ssid, '');
}
async function wifiConnect(ssid, pw) {
  if (pw && (pw.length < 8 || pw.length > 63)) {
    return overlay('La password del Wi-Fi deve avere almeno 8 caratteri', [['OK', hideOverlay]]);
  }
  state.busy = true;
  overlay(`Mi collego a «${ssid}»…`);
  const r = await api(`wifi?action=connect&ssid=${q(ssid)}&password=${q(pw || '')}`);
  state.busy = false;
  if (r && r.ok) overlay(`Collegato a «${ssid}»` + (r.ip ? ` (${r.ip})` : ''), [['OK', () => { hideOverlay(); wifiPage(); }]]);
  else overlay((r && r.error) || 'Collegamento non riuscito',
    [['Riprova', () => wifiChoose({ ssid, secure: !!pw }, false)], ['OK', hideOverlay]]);
}
async function wifiForget(ssid) {
  overlay(`Dimentico «${ssid}»…`);
  await api('wifi?action=forget&ssid=' + q(ssid));
  hideOverlay();
  wifiPage();
}

// ======================================================================== I miei siti
export async function sitiPage() {
  const list = $('#siti-list');
  list.innerHTML = '';
  list.appendChild(item('Scrivi un indirizzo…', 'Apri un sito qualsiasi', sitoNuovo));
  const r = await api('sites');
  ((r && r.sites) || []).forEach(x => list.appendChild(item(x.label,
    [x.url, x.mobile ? 'vista telefono' : '', x.home ? 'nella home' : ''].filter(Boolean).join(' · '),
    () => sitoScelto(x))));
  if (state.page === 'siti') (list.querySelector('[tabindex]') || list).focus();
}
function sitoNuovo() {
  window.__osk.open({
    title: 'Indirizzo del sito (es. www.la7.it)',
    value: store.get('ultimo-url') || '',
    onDone: v => {
      v = (v || '').trim();
      if (!v) return state.show('siti');
      store.set('ultimo-url', v);
      overlay(v, [['Apri', () => sitoApri(v)], ['Salva e apri', () => sitoSalva(v, true)],
        ['Salva', () => sitoSalva(v, false)], ['Annulla', hideOverlay]], 0);
    },
    onCancel: () => state.show('siti'),
  });
}
function sitoScelto(x, focus = 0) {
  overlay(x.label, [['Apri', () => sitoApri(x.url)],
    [x.home ? 'Togli dalla home' : 'Metti nella home', () => sitoOpzione(x, 'home', !x.home)],
    [x.mobile ? 'Vista: telefono' : 'Vista: computer', () => sitoVista(x)],
    ['Rimuovi', () => sitoRimuovi(x)], ['Annulla', hideOverlay]], focus);
}
async function sitoVista(x) {
  await api(`sites?action=mobile&on=${x.mobile ? 0 : 1}&url=${q(x.url)}`);
  x.mobile = !x.mobile;
  sitoScelto(x, 2);                                      // resta sul pulsante della vista
}
async function sitoOpzione(x, what, on) {
  await api(`sites?action=${what}&on=${on ? 1 : 0}&url=${q(x.url)}`);
  await rebuild();
  hideOverlay();
  sitiPage();
}
export async function sitoApri(u) {
  state.busy = true;
  overlay('Apertura di ' + u + '…');
  const r = await api('openurl?url=' + q(u));
  if (!r || !r.ok) { state.busy = false; return overlay((r && r.error) || 'Errore', [['OK', hideOverlay]]); }
  setTimeout(() => { state.busy = false; }, 8000);
}
async function sitoSalva(u, apri) {
  const r = await api('sites?action=add&url=' + q(u));
  if (!r || !r.ok) return overlay((r && r.error) || 'Errore', [['OK', hideOverlay]]);
  if (apri) sitoApri(u);
  else { hideOverlay(); sitiPage(); }
}
async function sitoRimuovi(x) {
  await api('sites?action=remove&url=' + q(x.url));
  await rebuild();
  hideOverlay();
  sitiPage();
}

// ======================================================================== Canali in diretta
// In alto i canali nella home, nell'ordine (OK: sposta / togli); sotto, per gruppo, quelli da
// aggiungere (OK: aggiunto in fondo). Ogni modifica ridisegna la home.
export async function channelsPage(focusId, r) {
  r = r || await api('channels');
  const list = $('#channels-list');
  list.innerHTML = '';
  if (!r) { list.appendChild(el('div', 'gwait', 'Servizio TV non raggiungibile')); return; }
  const all = {};
  r.groups.forEach(g => g.items.forEach(c => { all[c.id] = Object.assign({ group: g.title }, c); }));
  const head = t => list.appendChild(el('div', 'listhead', t));
  head('Nella home, in quest\'ordine');
  r.selected.forEach((id, i) => {
    const c = all[id];
    const b = item(`${i + 1}.  ${c.label}`, c.guide ? '' : 'senza guida TV', () => channelMenu(c, r.selected.length));
    b.dataset.cid = id;
    list.appendChild(b);
  });
  r.groups.forEach(g => {
    const rest = g.items.filter(c => !c.on);
    if (!rest.length) return;
    head(`${g.title} · da aggiungere`);
    rest.forEach(c => {
      const b = item('+  ' + c.label, c.guide ? 'OK per aggiungerlo alla home' : 'OK per aggiungerlo · senza guida TV',
        () => channelDo(c.id, 'add', c.id));
      b.dataset.cid = c.id;
      b.classList.add('off');
      list.appendChild(b);
    });
  });
  const f = focusId && list.querySelector(`[data-cid="${focusId}"]`);
  const t = f || list.querySelector('[tabindex]');
  if (t && state.page === 'channels') { t.focus(); t.scrollIntoView({ block: 'center' }); }
}
async function channelDo(id, action, focusId) {
  const r = await api(`channels?action=${action}&id=${q(id)}`);
  await rebuild();                                       // la home cambia subito
  hideOverlay();
  channelsPage(focusId, r);
  return r;
}
function channelMenu(c, n) {
  const opts = [];
  if (c.pos > 1) opts.push(['Sposta prima', async () => { await channelDo(c.id, 'up', c.id); }]);
  if (c.pos < n) opts.push(['Sposta dopo', async () => { await channelDo(c.id, 'down', c.id); }]);
  if (n > 1) opts.push(['Togli dalla home', () => channelDo(c.id, 'remove', null)]);
  overlay(`${c.label}\nn° ${c.pos} nella home`, opts.concat([['Annulla', hideOverlay]]), 0);
}

// ======================================================================== Schermata iniziale
export function homeEditPage(focusId) {
  const CFG = state.CFG, list = $('#homeedit-list'), hidden = new Set(CFG.hidden || []), where = {};
  const pinned = new Set(CFG.pinned || []), other = new Set(CFG.other || []);
  list.innerHTML = '';
  // i canali non sono qui: si scelgono in "Canali in diretta"
  CFG.sections.filter(sec => !sec.channels).forEach(sec => sec.items.forEach(id => { where[id] = sec.title || 'Home'; }));
  (CFG.other || []).forEach(id => { where[id] = where[id] || 'Altri servizi'; });
  const done = async (action, id) => {
    const r = await api(`home?action=${action}&id=${q(id)}`);
    if (r) { CFG.hidden = r.hidden; CFG.pinned = r.pinned; }
    hideOverlay();
    build();
    homeEditPage(id);
  };
  Object.keys(where).forEach(id => {
    const s = CFG.services[id];
    if (!s) return;
    const extra = other.has(id);                       // di Altri servizi: si può mettere anche in home
    if (id === 'impostazioni' && !extra) return;
    const stato = hidden.has(id) ? 'NASCOSTA' : pinned.has(id) ? 'in home e in Altri servizi' : 'visibile';
    const b = item(s.label, `${where[id]} · ${stato}`, () => {
      if (!extra) return done(hidden.has(id) ? 'show' : 'hide', id);
      const opts = [];
      if (!pinned.has(id) || hidden.has(id)) opts.push(['Anche in home', () => done('pin', id)]);
      if (pinned.has(id)) opts.push(['Solo in Altri servizi', () => done('unpin', id)]);
      if (!pinned.has(id) && hidden.has(id)) opts.push(['Mostra in Altri servizi', () => done('show', id)]);
      if (!hidden.has(id) && id !== 'impostazioni') opts.push(['Nascondi', async () => {
        if (pinned.has(id)) await api(`home?action=unpin&id=${q(id)}`);
        done('hide', id);
      }]);
      overlay(s.label, opts.concat([['Annulla', hideOverlay]]), 0);
    });
    b.dataset.hid = id;
    if (hidden.has(id)) b.classList.add('off');
    list.appendChild(b);
  });
  // i tuoi siti messi nella home (da "I miei siti"): si tolgono anche da qui
  (CFG.my_sites || []).forEach(x => {
    const b = item(x.label, 'Uno dei tuoi siti · nella home', () => overlay(x.label, [
      ['Togli dalla home', async () => {
        await api(`sites?action=home&on=0&url=${q(x.url)}`);
        await rebuild();
        hideOverlay();
        homeEditPage();
      }],
      ['Annulla', hideOverlay]], 0));
    b.dataset.hid = 'sito:' + x.url;
    list.appendChild(b);
  });
  const f = focusId && list.querySelector(`[data-hid="${focusId}"]`);
  (f || list.querySelector('[tabindex]')).focus();
}

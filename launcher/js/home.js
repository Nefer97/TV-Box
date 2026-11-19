// home.js — schermata iniziale: riquadri dei servizi, canali in diretta, dettaglio del
// programma selezionato, intestazione (saluto, data, meteo, orologio, rete).
import { $, api, edgeFade, el, hasTransparency, shade, state } from './core.js';

const ICONS = {
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  tv: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="20" height="13" rx="2"/><path d="M8 2l4 4 4-4"/></svg>',
  grid: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
  globe: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/></svg>',
  // simbolo di YouTube "in negativo": rettangolo bianco e triangolo rosso, per il riquadro rosso
  youtube: '<svg class="yt" viewBox="0 0 24 24"><rect x="1" y="4.6" width="22" height="14.8" rx="4.4" fill="#fff"/><path d="M9.7 8.6v6.8l5.9-3.4z" fill="#d61f26"/></svg>',
  radio: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="8" width="18" height="12" rx="2"/><circle cx="15.5" cy="14" r="2.5"/><path d="M7 12h4M7 16h4M6 8l10-5"/></svg>',
};
const NET_ICONS = {
  wifi: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M2 8.5a15 15 0 0 1 20 0M5 12a10 10 0 0 1 14 0M8.5 15.5a5 5 0 0 1 7 0"/><circle cx="12" cy="19" r="1.2" fill="currentColor"/></svg>',
  cable: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="7" y="3" width="10" height="8" rx="1.5"/><path d="M12 11v5M7 21h10M12 16v5"/></svg>',
  off: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M3 3l18 18M8.5 15.5a5 5 0 0 1 7 0M5 12a10 10 0 0 1 4-2.4M2 8.5A15 15 0 0 1 8 5.3"/></svg>',
};
// dopo questi servizi vanno i riquadri dei siti scelti dall'utente
const MAIN_SERVICES = ['raiplay', 'mediaset', 'youtube'];

// ---------- riquadri ----------
// parole del nome, anche quelle attaccate: "StreamingCommunity" -> Streaming, Community
const words = label => label.split(/\s+|(?<=[a-zà-ù])(?=[A-Z])/);
// il nome del riquadro: tra le parole attaccate si può andare a capo (<wbr>), non a metà parola
function labelEl(label) {
  const span = el('span', 'label');
  label.split(/(?<=[a-zà-ù])(?=[A-Z])/).forEach((part, i) => {
    if (i) span.appendChild(document.createElement('wbr'));
    span.appendChild(document.createTextNode(part));
  });
  return span;
}
function tile(id, s, big) {
  if (s.live) {                                      // canale in diretta: scheda condivisa
    const c = window.TVCards.live({ id, label: s.label, color: s.color });
    c.tabIndex = 0;
    if (s.onair) c.dataset.onair = s.onair;
    return c;
  }
  const t = el('div', 'tile ' + (big ? 'big' : 'small'));
  t.tabIndex = 0;
  t.dataset.id = id;
  t.style.background = `linear-gradient(160deg, ${s.color || '#334155'}, ${shade(s.color || '#334155')})`;
  t.innerHTML = ICONS[s.icon] || ICONS.play;
  t.appendChild(labelEl(s.label));
  if (big) t.appendChild(el('span', 'sub', s.subtitle || ''));   // sempre presente: riquadri allineati
  const site = s.no_logo ? null : (s.logo_url || s.url);           // logo vero del sito, se c'è
  if (big && site) {
    const box = el('div', 'logo'), img = new Image();
    img.onload = () => { t.classList.add('haslogo'); if (hasTransparency(img)) box.classList.add('bare'); };
    img.onerror = () => box.remove();
    img.src = '/api/icon?url=' + encodeURIComponent(site);
    box.appendChild(img);
    t.appendChild(box);
  }
  // nomi lunghi: carattere più piccolo, mai spezzati a metà (le parole attaccate contano separate)
  if (big && Math.max(...words(s.label).map(w => w.length)) > 10) t.querySelector('.label').classList.add('long');
  return t;
}

export function build() {
  // i riquadri si nascondono da "Riquadri della home"; i canali si scelgono da "Canali in diretta"
  const CFG = state.CFG, hidden = new Set(CFG.hidden || []);
  const ok = id => CFG.services[id] && !hidden.has(id);
  const known = id => !!CFG.services[id];
  const home = $('#page-home'), detail = $('#detail');
  document.body.appendChild(detail);                  // messo da parte prima di svuotare
  home.innerHTML = '';
  let bigDone = false;
  CFG.sections.forEach(sec => {
    const items = sec.items.filter(sec.channels ? known : ok);
    if (!items.length) return;
    const live = items.some(id => CFG.services[id].live);
    if (sec.title) {
      const h = el('h2', 'sec-title');
      if (live) h.appendChild(el('span', 'dot'));
      h.appendChild(document.createTextNode(sec.title));
      home.appendChild(h);
    }
    const row = el('div', 'row');
    if (live) {
      row.classList.add('scroller');
      row.addEventListener('scroll', () => edgeFade(row));
      setTimeout(() => edgeFade(row), 0);
    }
    items.forEach(id => row.appendChild(tile(id, CFG.services[id], sec.big)));
    if (live) {                                        // in fondo ai canali: la Guida TV
      const g = window.TVCards.action({ k: 'guide', ic: '☰', lbl: 'Guida TV', sub: 'Cosa c\'è dopo' });
      g.tabIndex = 0;
      g._act = () => state.show('guide');
      row.appendChild(g);
    }
    if (sec.big) {                                     // servizi di Altri servizi messi in home
      const altriTile = [...row.children].find(t => t.dataset.id === 'altri');
      (CFG.pinned || []).filter(ok).filter(id => !items.includes(id))
        .forEach(id => row.insertBefore(tile(id, CFG.services[id], true), altriTile || null));
    }
    if (sec.big) row.classList.add('bigrow');
    if (sec.big && !bigDone) {                         // i siti dell'utente dopo i servizi principali
      bigDone = true;
      const after = [...row.children].filter(t => MAIN_SERVICES.includes(t.dataset.id)).pop();
      const ref = after ? after.nextSibling : row.firstChild;
      (CFG.my_sites || []).forEach(x => {
        const t = tile('', { label: x.label, icon: 'globe', color: '#0e7490', url: x.url, subtitle: 'Uno dei tuoi siti' }, true);
        t.dataset.url = x.url;
        delete t.dataset.id;
        row.insertBefore(t, ref);
      });
    }
    if (sec.big && row.children.length > 5) row.classList.add('scroller');   // tanti riquadri: la fila scorre
    home.appendChild(row);
  });
  home.appendChild(detail);                            // il dettaglio sta sotto i canali
  const altri = $('#altri-row');
  altri.innerHTML = '';
  (CFG.other || []).filter(ok).forEach(id => altri.appendChild(tile(id, CFG.services[id], true)));
}

export async function rebuild() {
  const c = await api('config');
  if (c) { state.CFG = c; build(); updateOnAir(); }
}

// ---------- programmi in onda ----------
export async function updateOnAir() {
  const data = await api('onair');
  if (!data) return;
  state.ONAIR = data;
  const now = Date.now();
  document.querySelectorAll('.tvcard[data-onair]').forEach(c => window.TVCards.fill(c, data[c.dataset.onair], now));
  showDetail(document.activeElement);
}

// sotto i canali: titolo, orario e descrizione del programma scelto; la sua foto sullo sfondo
export function showDetail(t) {
  const box = $('#detail'), bg = $('#bgimg');
  const d = t && t.classList && t.classList.contains('tvcard') && state.ONAIR[t.dataset.onair];
  if (!d || !d.title || state.page !== 'home') {
    box.classList.remove('show'); bg.classList.remove('show');
    document.body.classList.remove('withdetail');
    return;
  }
  box.querySelector('.dch').textContent = state.CFG.services[t.dataset.id].label;
  box.querySelector('.dtitle').textContent = d.title;
  box.querySelector('.dtime').textContent = window.TVCards.span(d);
  box.querySelector('.ddesc').textContent = d.desc || '';
  box.classList.add('show');
  document.body.classList.add('withdetail');
  const big = d.image_big || d.image;                  // la foto grande, nitida a tutto schermo
  if (!big) { bg.classList.remove('show'); return; }
  if (bg.dataset.src !== big) {
    bg.dataset.src = big;
    if (d.image) bg.style.backgroundImage = `url("${d.image}")`;   // intanto la piccola
    const im = new Image();
    im.onload = () => { if (bg.dataset.src === big) bg.style.backgroundImage = `url("${big}")`; };
    im.src = big;
  }
  bg.classList.add('show');
}

// ---------- intestazione ----------
export function greeting() {
  const h = new Date().getHours();
  return h < 5 ? 'Buonanotte' : h < 13 ? 'Buongiorno' : h < 18 ? 'Buon pomeriggio' : 'Buonasera';
}
export function tick() {
  if (state.page === 'home') $('#title').textContent = greeting();
  const d = new Date();
  $('#clock').textContent = d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
  const s = d.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' });
  $('#datetext').textContent = s.charAt(0).toUpperCase() + s.slice(1);
}
export async function updateMeteo() {
  const m = await api('meteo');
  const box = $('#meteo'), city = $('#meteo-city');
  if (!m || !m.city) { box.textContent = ''; city.textContent = 'scegli la città'; return; }
  city.textContent = m.city;
  if (m.error || m.temp == null) { box.textContent = ''; return; }
  box.innerHTML = '· <span class="ic"></span><span class="t"></span>';
  box.querySelector('.ic').textContent = m.icon;
  box.querySelector('.t').textContent = `${m.temp}° ${m.text} a ${m.city}`;
}
export async function updateStatus() {
  const [w, i] = await Promise.all([api('wifi'), api('info')]);
  const box = $('#status'), ips = (i && i.ip) || [];
  let kind = 'off', text = 'Non connesso';
  // la rete usata davvero: con cavo e Wi-Fi insieme vince quella della strada predefinita
  if (i && i.wired && ips.length) { kind = 'cable'; text = 'Rete via cavo'; }
  else if (w && w.connected) { kind = 'wifi'; text = w.ssid; }
  else if (ips.length) { kind = 'cable'; text = 'Rete via cavo'; }
  box.className = kind === 'off' ? 'off' : '';
  box.innerHTML = NET_ICONS[kind];
  box.appendChild(el('span', '', text));
}

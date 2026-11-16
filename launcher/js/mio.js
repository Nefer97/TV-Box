// mio.js — sezione "Il mio catalogo": righe di locandine e pagina della serie, come Mediaset.
// Questo file NON va toccato per scrivere il connettore: i dati li prepara tvd in tvbox/mio.py
// (formati descritti lì). OK su un episodio lo apre a tutto schermo sul sito, MENU dal video
// riporta qui (#mio:<serie>). Grafica: le stesse classi CSS di Mediaset (app.css).
// Accesso al sito: pulsante "Accedi" / "Esci" in alto a destra (vedi login() più sotto).
import { $, api, el, overlay, hideOverlay, q, state } from './core.js';

let series = null;                 // la serie aperta (risposta di /api/mio?action=series)

const day = d => new Date(d).toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
const mins = s => (s ? Math.round(s / 60) + ' min' : '');
const meta = x => [x.category, ...(x.genres || [])].filter((v, i, a) => v && a.indexOf(v) === i).join(' · ');

// ---------- accesso al sito (login) ----------
// Lo stato arriva con le righe: {available, logged, required}. L'accesso vero si fa sul sito,
// che tvd apre a schermo; con MENU si torna qui e la pagina si ricarica già collegata.
function login() {
  if (state.busy) return;
  state.busy = true;
  overlay('Apro la pagina di accesso…\nCon MENU torni qui quando hai finito.');
  api('mio?action=login').then(r => {
    if (!r || !r.ok) { state.busy = false; overlay((r && r.error) || 'Non riuscito', [['OK', hideOverlay]]); return; }
    setTimeout(() => { state.busy = false; }, 8000);
  });
}

function logout() {
  overlay('Uscire dall\'account?', [
    ['Esci', async () => { overlay('Esco…'); await api('mio?action=logout'); hideOverlay(); mioPage(); }],
    ['Annulla', hideOverlay]], 1);
}

function account(l) {
  const b = $('#mio-account');
  b.textContent = '';
  b.removeAttribute('tabindex');
  if (!l || !l.available) return;
  b.textContent = l.logged ? 'Collegato · Esci' : 'Accedi';
  b.tabIndex = 0;
  b._act = l.logged ? logout : login;
}

// ---------- pagina con le righe ----------
function poster(x) {
  const c = el('div', 'poster');
  c.tabIndex = 0;
  c.style.backgroundImage = `url("${x.poster}")`;
  c.appendChild(el('div', 'ptitle', x.title));
  if (x.sub) c.appendChild(el('div', 'psub', x.sub));
  c._mio = x;                      // (non _info: quello lo legge la sezione Mediaset)
  c._act = () => openSeries(x.id, x.episode);
  return c;
}

export async function mioPage() {
  const box = $('#mio-rails');
  if (!box.children.length) box.appendChild(el('div', 'gwait', 'Carico il catalogo…'));
  const r = await api('mio');
  box.innerHTML = '';
  if (!r || !r.rails) { account(null); box.appendChild(el('div', 'gwait', 'Catalogo non disponibile')); return; }
  account(r.login);
  if (r.login && r.login.required && !r.login.logged) {
    box.appendChild(el('div', 'gwait', 'Accedi per vedere il catalogo (pulsante in alto a destra)'));
    if (state.page === 'mio') $('#mio-account').focus();
    return;
  }
  const rails = r.rails.filter(x => x.items.length);
  if (!rails.length) {
    box.appendChild(el('div', 'gwait', 'Nessun contenuto: il connettore è ancora vuoto (tvbox/mio.py, RAILS)'));
    if (state.page === 'mio' && $('#mio-account').tabIndex === 0) $('#mio-account').focus();
    return;
  }
  rails.forEach(rail => {
    const sec = el('div', 'msrail');
    sec.appendChild(el('h2', 'sec-title', rail.title));
    const row = el('div', 'row scroller');
    rail.items.forEach(x => row.appendChild(poster(x)));
    sec.appendChild(row);
    box.appendChild(sec);
  });
  const first = box.querySelector('.poster');
  if (first && state.page === 'mio') first.focus();
}

// logo del titolo (immagine) con il nome scritto come riserva
function setLogo(img, name, x) {
  name.textContent = x.title || '';
  img.classList.remove('ok');
  img.onload = () => img.classList.add('ok');
  img.onerror = () => img.classList.remove('ok');
  if (x.logo) img.src = x.logo; else img.removeAttribute('src');
}

// sfondo con dissolvenza: cambia solo quando la nuova immagine è pronta
let bgWant = '', bgTimer = 0;
function setBg(box, url) {
  bgWant = url || '';
  clearTimeout(bgTimer);
  bgTimer = setTimeout(() => {
    const want = bgWant;
    if (!want) { box.classList.remove('on'); return; }
    const im = new Image();
    im.onload = () => {
      if (bgWant !== want) return;
      box.classList.remove('on');
      setTimeout(() => { box.style.backgroundImage = `url("${want}")`; box.classList.add('on'); }, 180);
    };
    im.src = want;
  }, 220);
}

function detail(x) {
  setLogo($('#mio-logo'), $('#mio-name'), x);
  $('#mio-meta').textContent = x.sub ? `Continua a guardare · ${x.sub}` : meta(x);
  $('#mio-desc').textContent = x.desc || '';
  setBg($('#mio-bg'), x.hero);
}

// ---------- pagina della serie ----------
function openSeries(id, episode) {
  state.mioSeries = id;
  state.mioEpisode = episode || null;
  state.show('mioserie');
}

export async function mioSeriesPage() {
  const id = state.mioSeries;
  const list = $('#mios-eps');
  list.innerHTML = '';
  list.appendChild(el('div', 'gwait', 'Carico gli episodi…'));
  setLogo($('#mios-logo'), $('#mios-title'), {});
  $('#mios-info').textContent = '';
  $('#mios-desc').textContent = '';
  $('#mios-seasons').innerHTML = '';
  const r = await api(`mio?action=series&id=${q(id)}` + (state.mioSeason ? `&season=${q(state.mioSeason)}` : ''));
  state.mioSeason = null;
  if (!r || r.error) {
    list.innerHTML = '';
    list.appendChild(el('div', 'gwait', (r && r.error) || 'Non disponibile'));
    if (r && r.login && !r.login.logged) {                 // serve l'accesso: pulsante qui
      const b = el('div', 'btn chip', 'Accedi');
      b.tabIndex = 0;
      b._act = login;
      list.appendChild(b);
      if (state.page === 'mioserie') b.focus();
    }
    return;
  }
  series = r;
  $('#mios-hero').style.backgroundImage = r.hero ? `url("${r.hero}")` : '';
  setLogo($('#mios-logo'), $('#mios-title'), r);
  $('#mios-info').textContent = [meta(r), r.seasons.length > 1 ? `${r.seasons.length} stagioni` : '',
    r.episodes.length ? `${r.episodes.length} episodi` : ''].filter(Boolean).join(' · ');
  $('#mios-desc').textContent = r.desc || '';
  const ss = $('#mios-seasons');
  if (r.seasons.length > 1) {
    r.seasons.forEach(s => {
      const b = el('div', 'btn chip' + (s.id === r.season ? ' on' : ''), s.title || 'Stagione ' + s.n);
      b.tabIndex = 0;
      b._act = () => { state.mioSeason = s.id; mioSeriesPage(); };
      ss.appendChild(b);
    });
  }
  list.innerHTML = '';
  if (!r.episodes.length) list.appendChild(el('div', 'gwait', 'Nessun episodio disponibile'));
  const last = state.mioEpisode || r.last;
  const li = r.episodes.findIndex(e => e.id === last);
  r.episodes.forEach((e, i) => {
    const row = el('div', 'gprog msep');
    row.tabIndex = 0;
    const pic = el('div', 'gpic');
    if (e.image) pic.style.backgroundImage = `url("${e.image}")`;
    const body = el('div', 'gbody');
    const t = el('div', 'gtitle', e.title);
    if (i === li) t.appendChild(el('span', 'gnow seen', 'ULTIMO VISTO'));
    if (li > 0 && i === li - 1) t.appendChild(el('span', 'gnow', 'SUCCESSIVO'));
    body.append(t, el('div', 'ginfo', [e.date ? day(e.date) : '', e.channel, mins(e.dur)].filter(Boolean).join(' · ')));
    if (e.desc) body.appendChild(el('div', 'gdesc', e.desc));
    row.append(pic, body);
    row._act = () => play(e);
    list.appendChild(row);
  });
  // si parte dall'episodio dopo l'ultimo visto (la lista va dal più recente), altrimenti dal primo
  const rows = list.querySelectorAll('.msep');
  const start = li > 0 ? rows[li - 1] : rows[0];
  if (start && state.page === 'mioserie') { start.focus(); start.scrollIntoView({ block: 'center' }); }
}

async function play(e) {
  if (state.busy) return;
  state.busy = true;
  overlay(`${series.title}\n${e.title}`);
  const r = await api(`mio?action=play&url=${q(e.url)}&series=${q(series.id)}&title=${q(series.title)}` +
    `&poster=${q(series.poster)}&hero=${q(series.hero || '')}&logo=${q(series.logo || '')}` +
    `&episode=${q(e.id)}&n=${e.n == null ? '' : e.n}&ep=${q(e.title)}`);
  if (!r || !r.ok) { state.busy = false; overlay((r && r.error) || 'Non riuscito', [['OK', hideOverlay]]); return; }
  setTimeout(() => { state.busy = false; }, 8000);
}

// la locandina scelta: dettaglio in alto (lo scorrimento delle righe lo fa già mediaset.js)
document.addEventListener('focusin', ev => {
  const t = ev.target;
  if (t && t._mio) detail(t._mio);
});

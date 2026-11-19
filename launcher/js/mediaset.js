// mediaset.js — sezione Mediaset (fiction, serie, programmi, cartoni…): righe di locandine e pagina della serie.
// I dati arrivano da tvd (/api/mediaset, catalogo pubblico Mediaset); OK su un episodio lo apre
// a tutto schermo sul sito Mediaset, MENU dal video riporta qui (#ms:<serie>).
import { $, api, el, overlay, hideOverlay, q, showProgress, state } from './core.js';
import { lockPage, loginGate } from './login.js';

let series = null;                 // la serie aperta (risposta di /api/mediaset?action=series)

const hhmm = d => new Date(d).toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
const mins = s => (s ? Math.round(s / 60) + ' min' : '');

// ---------- pagina con le righe ----------
function poster(x) {
  const c = el('div', 'poster');
  c.tabIndex = 0;
  c.style.backgroundImage = `url("${x.poster}")`;
  c.appendChild(el('div', 'ptitle', x.title));
  if (x.sub) c.appendChild(el('div', 'psub', x.sub));
  c._info = x;
  c._act = () => openSeries(x.id, x.episode);
  return c;
}

// ---------- accesso (login) ----------
// Senza accesso la sezione mostra solo la schermata di accesso (login.js); l'accesso lo fa tvd
// con la libreria del sito Mediaset. "Esci" sta in Impostazioni → Rete e assistenza.
async function locked() {
  const l = await api('mediaset?action=status');
  return l && l.required && !l.logged ? l : null;
}
function showLogin(l) {
  lockPage('mediaset', true);
  loginGate($('#ms-login'), {
    id: 'mediaset', endpoint: 'mediaset', userLabel: 'Email', user: l && l.user,
    onDone: () => { lockPage('mediaset', false); $('#ms-rails').innerHTML = ''; msPage(); },
  });
}

export async function msPage() {
  const box = $('#ms-rails');
  const l = await locked();
  if (l) return showLogin(l);
  lockPage('mediaset', false);
  if (!box.children.length) box.appendChild(el('div', 'gwait', 'Carico il catalogo Mediaset…'));
  const r = await api('mediaset');
  box.innerHTML = '';
  if (!r || !r.rails) { box.appendChild(el('div', 'gwait', 'Catalogo Mediaset non disponibile')); return; }
  r.rails.filter(x => x.items.length).forEach(rail => {
    const sec = el('div', 'msrail');
    sec.appendChild(el('h2', 'sec-title', rail.title));
    const row = el('div', 'row scroller');
    rail.items.forEach(x => row.appendChild(poster(x)));
    sec.appendChild(row);
    box.appendChild(sec);
  });
  const first = box.querySelector('.poster');
  if (first && state.page === 'mediaset') first.focus();
}

// logo della serie (immagine) con il titolo scritto come riserva
function setLogo(img, name, x) {
  name.textContent = x.title || '';
  img.classList.remove('ok');
  img.onload = () => img.classList.add('ok');
  img.onerror = () => img.classList.remove('ok');
  if (x.logo) img.src = x.logo; else img.removeAttribute('src');
}
const meta = x => [x.category, ...(x.genres || [])].filter((v, i, a) => v && a.indexOf(v) === i).join(' · ');

// sfondo con dissolvenza: cambia solo quando la nuova immagine è pronta
let bgWant = '', bgTimer = 0;
function setBg(box, url) {
  bgWant = url || '';
  clearTimeout(bgTimer);
  bgTimer = setTimeout(() => {                 // scorrendo veloce non si scaricano tutte le immagini
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

// in alto: immagine, logo, generi e trama della locandina scelta
function msDetail(t) {
  const x = t && t._info;
  if (!x) return;
  setLogo($('#ms-logo'), $('#ms-name'), x);
  $('#ms-meta').textContent = x.sub ? `Continua a guardare · ${x.sub}` : meta(x);
  $('#ms-desc').textContent = x.desc || '';
  setBg($('#ms-bg'), x.hero);
}

// orologio piccolo in alto (le pagine Mediaset non hanno l'intestazione)
function clock() {
  const t = new Date().toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
  document.querySelectorAll('.msclock').forEach(e => { e.textContent = t; });
}
clock();
setInterval(clock, 10000);

// ---------- pagina della serie ----------
async function openSeries(id, episode) {
  state.msSeries = id;
  state.msEpisode = episode || null;
  state.show('msserie');
}

export async function seriesPage() {
  if (await locked()) return state.show('mediaset');   // senza accesso: la schermata di accesso
  const id = state.msSeries;
  const list = $('#mss-eps');
  list.innerHTML = '';
  list.appendChild(el('div', 'gwait', 'Carico gli episodi…'));
  setLogo($('#mss-logo'), $('#mss-title'), {});
  $('#mss-info').textContent = '';
  $('#mss-desc').textContent = '';
  $('#mss-seasons').innerHTML = '';
  const r = await api(`mediaset?action=series&id=${q(id)}` + (state.msSeason ? `&season=${q(state.msSeason)}` : ''));
  state.msSeason = null;
  if (!r || r.error) { list.innerHTML = ''; list.appendChild(el('div', 'gwait', (r && r.error) || 'Non disponibile')); return; }
  series = r;
  $('#mss-hero').style.backgroundImage = r.hero ? `url("${r.hero}")` : '';
  setLogo($('#mss-logo'), $('#mss-title'), r);
  $('#mss-info').textContent = [meta(r), r.seasons.length > 1 ? `${r.seasons.length} stagioni` : '',
    r.episodes.length ? `${r.episodes.length} episodi gratuiti` : ''].filter(Boolean).join(' · ');
  $('#mss-desc').textContent = r.desc;
  const ss = $('#mss-seasons');
  if (r.seasons.length > 1) {
    r.seasons.forEach(s => {
      const b = el('div', 'btn chip' + (s.guid === r.season ? ' on' : ''), 'Stagione ' + s.n);
      b.tabIndex = 0;
      b._act = () => { state.msSeason = s.guid; seriesPage(); };
      ss.appendChild(b);
    });
  }
  const prog = (await api('progress')) || {};
  list.innerHTML = '';
  if (!r.episodes.length) list.appendChild(el('div', 'gwait', 'Nessun episodio gratuito disponibile'));
  const last = state.msEpisode || r.last;
  const li = r.episodes.findIndex(e => e.id === last);
  // il successivo dell'ultimo visto: dopo nella lista se gli episodi vanno dal primo (ascending),
  // prima se vanno dal più recente
  const ni = li < 0 ? -1 : li + (r.ascending ? 1 : -1);
  r.episodes.forEach((e, i) => {
    const row = el('div', 'gprog msep');
    row.tabIndex = 0;
    const pic = el('div', 'gpic');
    if (e.image) pic.style.backgroundImage = `url("${e.image}")`;
    const body = el('div', 'gbody');
    const t = el('div', 'gtitle', e.title);
    if (i === li) t.appendChild(el('span', 'gnow seen', 'ULTIMO VISTO'));
    if (ni >= 0 && i === ni) t.appendChild(el('span', 'gnow', 'SUCCESSIVO'));
    body.append(t, el('div', 'ginfo', [e.date ? hhmm(e.date) : '', e.channel, mins(e.dur)].filter(Boolean).join(' · ')));
    if (e.desc) body.appendChild(el('div', 'gdesc', e.desc));
    showProgress(pic, t, prog[e.url]);
    row.dataset.url = e.url;
    row.append(pic, body);
    row._act = () => play(e);
    list.appendChild(row);
  });
  // si parte dall'episodio dopo l'ultimo visto (la lista va dal più recente), altrimenti dal più recente
  const rows = list.querySelectorAll('.msep');
  const start = rows[ni] || rows[li] || rows[0];   // il successivo, o l'ultimo visto, o il primo della lista
  if (start && state.page === 'msserie') { start.focus(); start.scrollIntoView({ block: 'center' }); }
}

async function play(e) {
  if (state.busy) return;
  state.busy = true;
  overlay(`${series.title}\n${e.title}`);
  const r = await api(`mediaset?action=play&url=${q(e.url)}&series=${q(series.id)}&title=${q(series.title)}` +
    `&poster=${q(series.poster)}&hero=${q(series.hero || '')}&logo=${q(series.logo || '')}` +
    `&episode=${q(e.id)}&n=${e.n == null ? '' : e.n}&ep=${q(e.title)}&season=${q(series.season || '')}`);
  if (!r || !r.ok) { state.busy = false; overlay((r && r.error) || 'Non riuscito', [['OK', hideOverlay]]); return; }
  setTimeout(() => { state.busy = false; }, 8000);
}

// la locandina scelta: dettaglio in alto e riga visibile (la pagina scorre in verticale)
document.addEventListener('focusin', ev => {
  const t = ev.target;
  if (t.classList && t.classList.contains('poster')) {
    msDetail(t);
    const rail = t.closest('.msrail');
    if (rail) rail.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  if (t.classList && t.classList.contains('msep')) t.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
});

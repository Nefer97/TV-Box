// mediaset.js — sezione Mediaset (fiction e serie): righe di locandine e pagina della serie.
// I dati arrivano da tvd (/api/mediaset, catalogo pubblico Mediaset); OK su un episodio lo apre
// a tutto schermo sul sito Mediaset, MENU dal video riporta qui (#ms:<serie>).
import { $, api, el, overlay, hideOverlay, q, state } from './core.js';

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

export async function msPage() {
  const box = $('#ms-rails');
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

// in alto: titolo e trama della locandina scelta
function msDetail(t) {
  const d = $('#ms-detail'), x = t && t._info;
  if (!x) return;
  d.querySelector('.dch').textContent = x.sub ? 'Continua · ' + x.sub : (x.category || 'Mediaset Infinity');
  d.querySelector('.dtitle').textContent = x.title;
  d.querySelector('.ddesc').textContent = x.desc || '';
}

// ---------- pagina della serie ----------
async function openSeries(id, episode) {
  state.msSeries = id;
  state.msEpisode = episode || null;
  state.show('msserie');
}

export async function seriesPage() {
  const id = state.msSeries;
  const list = $('#mss-eps');
  list.innerHTML = '';
  list.appendChild(el('div', 'gwait', 'Carico gli episodi…'));
  $('#mss-title').textContent = '';
  $('#mss-desc').textContent = '';
  $('#mss-seasons').innerHTML = '';
  const r = await api(`mediaset?action=series&id=${q(id)}` + (state.msSeason ? `&season=${q(state.msSeason)}` : ''));
  state.msSeason = null;
  if (!r || r.error) { list.innerHTML = ''; list.appendChild(el('div', 'gwait', (r && r.error) || 'Non disponibile')); return; }
  series = r;
  $('#mss-hero').style.backgroundImage = r.hero ? `url("${r.hero}")` : '';
  $('#mss-title').textContent = r.title;
  $('#mss-info').textContent = [r.category, r.seasons.length > 1 ? `${r.seasons.length} stagioni` : '',
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
  list.innerHTML = '';
  if (!r.episodes.length) list.appendChild(el('div', 'gwait', 'Nessun episodio gratuito disponibile'));
  const last = state.msEpisode || r.last;
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
    body.append(t, el('div', 'ginfo', [e.date ? hhmm(e.date) : '', e.channel, mins(e.dur)].filter(Boolean).join(' · ')));
    if (e.desc) body.appendChild(el('div', 'gdesc', e.desc));
    row.append(pic, body);
    row._act = () => play(e);
    list.appendChild(row);
  });
  // si parte dall'episodio dopo l'ultimo visto (la lista va dal più recente), altrimenti dal più recente
  const rows = list.querySelectorAll('.msep');
  const start = li > 0 ? rows[li - 1] : li === 0 ? rows[0] : rows[0];
  if (start && state.page === 'msserie') { start.focus(); start.scrollIntoView({ block: 'center' }); }
}

async function play(e) {
  if (state.busy) return;
  state.busy = true;
  overlay(`${series.title}\n${e.title}`);
  const r = await api(`mediaset?action=play&url=${q(e.url)}&series=${q(series.id)}&title=${q(series.title)}` +
    `&poster=${q(series.poster)}&episode=${q(e.id)}&n=${e.n == null ? '' : e.n}`);
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


// mio.js — catalogo con HOME, SERIE TV e FILM.
// I dati del catalogo vengono preparati da tvbox/mio.py.
// La riproduzione e la pagina dei dettagli restano invariate.

import { $, api, el, overlay, hideOverlay, q, showProgress, state } from './core.js';
import { lockPage, loginGate } from './login.js';

let series = null;

// ---------- navigazione catalogo ----------

let catalogRails = {};             // righe già caricate, per pagina: { home: [...], series: [...] }
let activeCatalogPage = 'home';
let searchQuery = '';
let searchResults = null;
let searchBusy = false;
let searchRequest = 0;
let catalogLoaded = 0;
const CATALOG_TTL = 30 * 60 * 1000;

const catalogPages = [
  { id: 'home', title: 'HOME' },
  { id: 'series', title: 'SERIE TV' },
  { id: 'films', title: 'FILM' }
];

const day = d => new Date(d).toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
const mins = s => (s ? Math.round(s / 60) + ' min' : '');
const meta = x => [x.category, ...(x.genres || [])].filter((v, i, a) => v && a.indexOf(v) === i).join(' · ');

// ---------- accesso (login) ----------
// Senza accesso la sezione mostra solo la schermata di accesso (login.js); l'accesso lo fa tvd.
// "Esci" sta in Impostazioni → Rete e assistenza → Account.

function showLogin(l) {
  lockPage('mio', true);
  loginGate($('#mio-login'), {
    id: 'mio', endpoint: 'mio', userLabel: 'Utente', user: l && l.user,
    onDone: () => { lockPage('mio', false); $('#mio-rails').innerHTML = ''; mioPage(); },
  });
}

// ---------- locandina ----------

function poster(x) {
  const c = el('div', 'poster');
  c.tabIndex = 0;
  c.style.backgroundImage = `url("${x.poster}")`;
  c.appendChild(el('div', 'ptitle', x.title));
  if (x.sub) c.appendChild(el('div', 'psub', x.sub));
  c._mio = x;
  c._act = () => openSeries(x.id, x.episode);
  return c;
}

// ---------- barra di ricerca ----------

function renderSearchBar() {
  const bar = el('div', 'mio-search');

  // un pulsante come gli altri (le frecce ci arrivano per posizione): OK apre la tastiera a
  // schermo, "Fatto" cerca. Nel launcher niente <input>: il telecomando non ha lettere.
  const field = el('div', 'btn mio-search-field' + (searchQuery ? '' : ' empty'),
    searchQuery ? `🔍  ${searchQuery}` : '🔍  Cerca film o serie TV…');
  field.tabIndex = 0;
  field.setAttribute('aria-label', 'Cerca per nome');
  field._act = openSearchKeyboard;
  bar.appendChild(field);

  if (searchQuery || searchResults !== null) {
    const clear = el('div', 'btn chip', 'Cancella');
    clear.tabIndex = 0;
    clear._act = clearSearch;
    bar.appendChild(clear);
  }
  return bar;
}

const focusSearch = () => {
  const f = $('#mio-rails .mio-search-field');
  if (f && state.page === 'mio') f.focus();
};

function openSearchKeyboard() {
  if (!window.__osk) return;
  window.__osk.open({
    title: 'Cerca per nome',
    value: searchQuery,
    onDone: v => {
      searchQuery = (v || '').trim();
      if (!searchQuery) return clearSearch();
      runSearch();
    },
    onCancel: focusSearch,
  });
}

function clearSearch() {
  searchQuery = '';
  searchResults = null;
  searchRequest++;                       // una ricerca ancora in corso non riscrive la pagina
  searchBusy = false;
  renderCatalogPage();
  focusSearch();
}

async function runSearch() {
  const query = searchQuery.trim();
  if (!query || searchBusy) return;

  searchBusy = true;
  searchResults = null;

  const request = ++searchRequest;
  renderCatalogPage();

  const r = await api(`mio?action=search&q=${q(query)}`);

  if (request !== searchRequest) return;

  searchBusy = false;
  searchResults = r && Array.isArray(r.items) ? r.items : [];

  renderCatalogPage();

  const first = $('#mio-rails').querySelector('.poster');
  if (first && state.page === 'mio') first.focus();
}


// ---------- rendering delle tre pagine ----------

const emptyMessages = {
  home: 'Nessuno slider disponibile al momento',
  series: 'Nessuna serie TV disponibile',
  films: 'Nessun film disponibile'
};

// focusTab: dopo il cambio di scheda il focus resta sulla scheda scelta,
// così con destra/sinistra si scorrono le schede senza risalire ogni volta.
function renderCatalogPage(focusTab = false) {
  const box = $('#mio-rails');
  box.innerHTML = '';

  // Navigazione HOME / SERIE TV / FILM
  const nav = el('div', 'row mio-tabs');

  catalogPages.forEach(page => {
    const tab = el('div', 'btn chip' + (activeCatalogPage === page.id ? ' on' : ''), page.title);
    tab.tabIndex = 0;
    tab._act = () => {
      if (activeCatalogPage === page.id && catalogRails[page.id]) return;
      activeCatalogPage = page.id;
      showCatalogPage(true);
    };
    nav.appendChild(tab);
  });

  box.appendChild(nav);
  box.appendChild(renderSearchBar());
  if (searchResults !== null || searchBusy) {
    if (searchBusy) {
      box.appendChild(el('div', 'gwait', 'Cerco nel catalogo…'));
    } else if (!searchResults.length) {
      box.appendChild(el('div', 'gwait', 'Nessun risultato trovato'));
    } else {
      const sec = el('div', 'msrail');
      sec.appendChild(el('h2', 'sec-title', `Risultati per "${searchQuery}"`));

      const row = el('div', 'row scroller');
      searchResults.forEach(x => row.appendChild(poster(x)));

      sec.appendChild(row);
      box.appendChild(sec);
    }

    if (state.page === 'mio') {
      const first = box.querySelector('.poster');
      if (first && !focusTab) first.focus();
    }
    return;
  }

  const activeTab = nav.children[catalogPages.findIndex(p => p.id === activeCatalogPage)];
  const rails = catalogRails[activeCatalogPage];

  if (!rails) {
    box.appendChild(el('div', 'gwait', 'Carico il catalogo…'));
  } else if (!rails.length) {
    box.appendChild(el('div', 'gwait', emptyMessages[activeCatalogPage]));
  } else {
    rails.forEach(rail => {
      const sec = el('div', 'msrail');
      sec.appendChild(el('h2', 'sec-title', rail.title));
      const row = el('div', 'row scroller');
      rail.items.forEach(x => row.appendChild(poster(x)));
      sec.appendChild(row);
      box.appendChild(sec);
    });
  }

  if (state.page !== 'mio') return;
  const first = box.querySelector('.poster');
  if (focusTab || !first) activeTab.focus();
  else first.focus();
}

// Mostra la scheda attiva; se non è ancora caricata la chiede a tvd.
async function showCatalogPage(focusTab = false) {
  const page = activeCatalogPage;
  renderCatalogPage(focusTab);
  if (catalogRails[page]) return;

  const r = await api(`mio?page=${q(page)}`);
  if (!r || !r.rails) {
    if (activeCatalogPage === page) {
      const wait = $('#mio-rails .gwait');
      if (wait) wait.textContent = 'Catalogo non disponibile';
    }
    return;
  }

  catalogRails[page] = r.rails.filter(rail => rail.items && rail.items.length);
  if (activeCatalogPage !== page || state.page !== 'mio') return;

  // se nel frattempo l'utente si è spostato su una scheda, il focus resta lì
  const onTab = document.activeElement && document.activeElement.closest('.mio-tabs');
  renderCatalogPage(focusTab || !!onTab);
}

// ---------- caricamento catalogo ----------

export async function mioPage() {
  const box = $('#mio-rails');

  const l = await api('mio?action=status');          // collegati? (ricontrollato ogni 5 minuti)
  if (l && l.required && !l.logged) return showLogin(l);
  lockPage('mio', false);

  if (!box.children.length) {
    box.appendChild(el('div', 'gwait', 'Carico il catalogo…'));
  }

  // la HOME si ricarica sempre (Continua a guardare cambia dopo ogni visione);
  // la scheda attiva resta quella di prima, così tornando da un titolo si è dove si era
  const r = await api('mio?page=home');

  box.innerHTML = '';

  if (!r || !r.rails) {
    box.appendChild(el('div', 'gwait', 'Catalogo non disponibile'));
    return;
  }

  if (r.login && r.login.required && !r.login.logged) return showLogin(r.login);

  if (Date.now() - catalogLoaded > CATALOG_TTL) {   // SERIE TV e FILM: al massimo 30 minuti
    catalogRails = {};
    catalogLoaded = Date.now();
  }
  catalogRails.home = r.rails.filter(rail => rail.items && rail.items.length);
  showCatalogPage();
}

// ---------- logo del titolo ----------

function setLogo(img, name, x) {
  name.textContent = x.title || '';
  img.classList.remove('ok');
  img.onload = () => img.classList.add('ok');
  img.onerror = () => img.classList.remove('ok');
  if (x.logo) img.src = x.logo;
  else img.removeAttribute('src');
}

// ---------- sfondo con dissolvenza ----------

let bgWant = '', bgTimer = 0;

function setBg(box, url) {
  bgWant = url || '';
  clearTimeout(bgTimer);

  bgTimer = setTimeout(() => {
    const want = bgWant;

    if (!want) {
      box.classList.remove('on');
      return;
    }

    const im = new Image();

    im.onload = () => {
      if (bgWant !== want) return;

      box.classList.remove('on');

      setTimeout(() => {
        box.style.backgroundImage = `url("${want}")`;
        box.classList.add('on');
      }, 180);
    };

    im.src = want;
  }, 220);
}

// ---------- dettagli titolo ----------

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

  const r = await api(
    `mio?action=series&id=${q(id)}` +
    (state.mioSeason ? `&season=${q(state.mioSeason)}` : '')
  );

  state.mioSeason = null;

  if (!r || r.error) {
    list.innerHTML = '';
    list.appendChild(el('div', 'gwait', (r && r.error) || 'Non disponibile'));

    if (r && r.login && r.login.required && !r.login.logged && state.page === 'mioserie') state.show('mio');

    return;
  }

  series = r;

  $('#mios-hero').style.backgroundImage = r.hero ? `url("${r.hero}")` : '';
  setLogo($('#mios-logo'), $('#mios-title'), r);

  $('#mios-info').textContent = [
    meta(r),
    r.seasons.length > 1 ? `${r.seasons.length} stagioni` : '',
    r.episodes.length ? `${r.episodes.length} episodi` : ''
  ].filter(Boolean).join(' · ');

  $('#mios-desc').textContent = r.desc || '';

  const ss = $('#mios-seasons');

  if (r.seasons.length > 1) {
    r.seasons.forEach(s => {
      const b = el(
        'div',
        'btn chip' + (s.id === r.season ? ' on' : ''),
        s.title || 'Stagione ' + s.n
      );

      b.tabIndex = 0;
      b._act = () => {
        state.mioSeason = s.id;
        mioSeriesPage();
      };

      ss.appendChild(b);
    });
  }

  list.innerHTML = '';

  if (!r.episodes.length) {
    list.appendChild(el('div', 'gwait', 'Nessun episodio disponibile'));
  }

  const prog = (await api('progress')) || {};      // dove si è arrivati (salvato da tvd)

  const last = state.mioEpisode || r.last;
  const li = r.episodes.findIndex(e => e.id === last);

  r.episodes.forEach((e, i) => {
    const row = el('div', 'gprog msep');
    row.tabIndex = 0;

    const pic = el('div', 'gpic');
    if (e.image) pic.style.backgroundImage = `url("${e.image}")`;

    const body = el('div', 'gbody');
    const seasonNumber = r.season ?? r.season_number ?? '';
    const episodeNumber = e.n ?? '';

    const prefix = seasonNumber !== '' && episodeNumber !== ''
      ? `S${seasonNumber}:E${episodeNumber} `
      : '';

    const t = el('div', 'gtitle', prefix + e.title);

    if (i === li) t.appendChild(el('span', 'gnow seen', 'ULTIMO VISTO'));
    if (li > 0 && i === li - 1) t.appendChild(el('span', 'gnow', 'SUCCESSIVO'));

    body.append(
      t,
      el('div', 'ginfo', [
        e.date ? day(e.date) : '',
        e.channel,
        mins(e.dur)
      ].filter(Boolean).join(' · '))
    );

    showProgress(pic, t, prog[e.url]);
    row.dataset.url = e.url;

    if (e.desc) body.appendChild(el('div', 'gdesc', e.desc));

    row.append(pic, body);
    row._act = () => play(e);

    list.appendChild(row);
  });

  // Si parte dall'episodio dopo l'ultimo visto, oppure dal primo.
  const rows = list.querySelectorAll('.msep');
  const start = li > 0 ? rows[li - 1] : rows[0];

  if (start && state.page === 'mioserie') {
    start.focus();
    start.scrollIntoView({ block: 'center' });
  }
}

// ---------- riproduzione: invariata ----------

async function play(e) {
  if (state.busy) return;

  state.busy = true;
  overlay(`${series.title}\n${e.title}`);

  const r = await api(
    `mio?action=play&url=${q(e.url)}&series=${q(series.id)}&title=${q(series.title)}` +
    `&poster=${q(series.poster)}&hero=${q(series.hero || '')}&logo=${q(series.logo || '')}` +
    `&episode=${q(e.id)}&n=${e.n == null ? '' : e.n}&ep=${q(e.title)}`
  );

  if (!r || !r.ok) {
    state.busy = false;
    overlay((r && r.error) || 'Non riuscito', [['OK', hideOverlay]]);
    return;
  }

  setTimeout(() => { state.busy = false; }, 8000);
}

// ---------- aggiornamento dettaglio locandina ----------

document.addEventListener('focusin', ev => {
  const t = ev.target;
  if (t && t._mio) detail(t._mio);
});

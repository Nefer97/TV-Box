// login.js — schermata di accesso di un servizio (Il mio catalogo; poi Mediaset).
// Utente e password si scrivono con la tastiera a schermo; l'accesso lo fa tvd (nessuna pagina
// del sito a schermo) e la password non si salva. Uso:
//   loginGate(box, { id: 'mio', endpoint: 'mio', userLabel: 'Utente', onDone: () => ... })
import { $, api, el, hideOverlay, overlay, q, shade, state } from './core.js';

const dots = s => '•'.repeat(Math.min(s.length, 16));

export function loginGate(box, o) {
  const s = state.CFG.services[o.id] || {};
  const name = s.label || o.id;
  const page = state.page;
  let user = o.user || '', pw = '';

  box.innerHTML = '';
  const wrap = el('div', 'login');

  // a sinistra il riquadro del servizio, come nella home
  const card = el('div', 'lcard');
  card.style.background = `linear-gradient(160deg, ${s.color || '#334155'}, ${shade(s.color || '#334155')})`;
  // logo vero del sito su fondo bianco; finché non c'è (o se manca) il simbolo ▶ come nella home
  card.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
  const site = s.no_logo ? null : (s.logo_url || s.url);
  if (site) {
    const img = new Image();
    img.onload = () => card.classList.add('haslogo');
    img.src = '/api/icon?url=' + encodeURIComponent(site);
    card.appendChild(img);
  }
  const ln = el('span', 'lname', name);
  if (Math.max(...name.split(/\s+/).map(w => w.length)) > 12) ln.classList.add('long');   // mai spezzato a metà
  card.appendChild(ln);
  wrap.appendChild(card);

  // a destra il modulo
  const form = el('div', 'lform');
  form.appendChild(el('div', 'ltitle', 'Accedi'));
  form.appendChild(el('div', 'lsub', `Entra con il tuo account ${name} per vedere il catalogo.`));
  const field = (label, value) => {
    const f = el('div', 'btn lfield');
    f.tabIndex = 0;
    f.appendChild(el('span', 'lk', label));
    f.appendChild(el('span', 'lv'));
    const set = v => {
      f.querySelector('.lv').textContent = v || 'Scrivi qui';
      f.classList.toggle('empty', !v);
    };
    set(value);
    f._set = set;
    form.appendChild(f);
    return f;
  };
  const fu = field(o.userLabel || 'Utente', user);
  const fp = field('Password', '');
  const go = el('div', 'btn lgo', 'Accedi');
  go.tabIndex = 0;
  form.appendChild(go);
  const err = el('div', 'lerr');
  form.appendChild(err);
  wrap.appendChild(form);
  box.appendChild(wrap);

  const here = f => { if (state.page === page) f.focus(); };
  const askUser = then => window.__osk.open({
    title: `${o.userLabel || 'Utente'} di ${name}`, value: user,
    onDone: v => { user = v.trim(); fu._set(user); err.textContent = ''; then ? then() : here(fp); },
    onCancel: () => here(fu),
  });
  const askPw = () => window.__osk.open({
    title: `Password di ${name}`, secret: true,
    onDone: v => { pw = v; fp._set(dots(pw)); err.textContent = ''; here(go); },
    onCancel: () => here(fp),
  });
  fu._act = () => askUser(askPw);              // dopo l'utente si passa subito alla password
  fp._act = askPw;
  go._act = async () => {
    if (state.busy) return;
    if (!user) { err.textContent = `Scrivi ${(o.userLabel || 'utente').toLowerCase()} e password`; return here(fu); }
    if (!pw) { err.textContent = 'Scrivi la password'; return here(fp); }
    state.busy = true;
    overlay('Accesso in corso…');
    const r = await api(`${o.endpoint}?action=login&user=${q(user)}&password=${q(pw)}`);
    state.busy = false;
    pw = '';
    fp._set('');
    hideOverlay();
    if (r && r.ok) return o.onDone(r);
    err.textContent = (r && r.error) || 'Accesso non riuscito';
    here(fp);
  };
  here(user ? fp : fu);
}

// sezione chiusa finché non si accede: la pagina mostra solo la schermata di accesso
export function lockPage(id, locked) {
  const p = $('#page-' + id);
  if (p) p.classList.toggle('locked', locked);
}

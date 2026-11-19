// check.mjs — prove della grafica: apre le pagine del launcher in Chromium (senza schermo),
// preme i tasti come il telecomando e controlla che le cose ci siano e abbiano la misura giusta.
// Si ferma (codice 1) al primo errore JavaScript o controllo fallito.
//   node tools/uitest/check.mjs <porta DevTools> <porta server> <cartella foto>
import fs from 'fs';

const [cdpPort, srvPort, shots] = process.argv.slice(2);
const BASE = `http://127.0.0.1:${srvPort}/`;
const tabs = await (await fetch(`http://127.0.0.1:${cdpPort}/json`)).json();
const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
await new Promise(r => { ws.onopen = r; });
let id = 0;
const wait = {}, errors = [];
ws.onmessage = m => {
  const d = JSON.parse(m.data);
  if (d.method === 'Runtime.exceptionThrown') errors.push(d.params.exceptionDetails.exception?.description?.split('\n')[0]);
  if (d.id && wait[d.id]) wait[d.id](d.result || d);
};
const call = (method, params = {}) => new Promise(r => { wait[++id] = r; ws.send(JSON.stringify({ id, method, params })); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const js = async e => (await call('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })).result?.value;
const KEYS = { up: ['ArrowUp', 38], down: ['ArrowDown', 40], left: ['ArrowLeft', 37], right: ['ArrowRight', 39],
  ok: ['Enter', 13], back: ['Escape', 27] };
async function press(...ks) {
  for (const k of ks) {
    const [key, code] = KEYS[k];
    for (const type of ['rawKeyDown', 'keyUp']) await call('Input.dispatchKeyEvent', { type, key, code: key, windowsVirtualKeyCode: code });
    await sleep(300);
  }
}
async function open(hash) {
  await call('Page.navigate', { url: 'about:blank' });
  await sleep(300);
  await call('Page.navigate', { url: BASE + (hash ? '#' + hash : '') });
}
// aspetta che un'espressione sia vera (dati dalla rete: fino a 15 s)
async function until(expr, ms = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (await js(expr)) return true; await sleep(300); }
  return false;
}
let failed = 0;
async function check(name, expr, ms) {
  const ok = await until(expr, ms);
  console.log(`${ok ? '  ok ' : ' ERR '} ${name}`);
  if (!ok) failed++;
}
async function shot(name) {
  const r = await call('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(`${shots}/${name}.png`, Buffer.from(r.data, 'base64'));
}
// nessuna scheda più alta di un terzo dello schermo (es. la "Guida TV" gigante della V2)
const SIZES = `[...document.querySelectorAll('.tvcard, .poster, .tile')].every(e => e.offsetParent === null || e.getBoundingClientRect().height < innerHeight / 2.2)`;

await call('Runtime.enable');
// senza schermo la pagina non è "in primo piano": la selezione iniziale (focus) non scatterebbe
await call('Emulation.setFocusEmulationEnabled', { enabled: true });
await call('Emulation.setDeviceMetricsOverride', { width: 1280, height: 720, deviceScaleFactor: 1, mobile: false });
// identità di un Chrome normale: alcuni siti negano le immagini a "Chrome senza schermo"
await call('Emulation.setUserAgentOverride', { userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36' });

console.log('home');
await open('');
await check('riquadri principali', `document.querySelectorAll('#page-home .tile.big').length >= 4`);
await check('canali in diretta con il programma', `[...document.querySelectorAll('.tvcard[data-onair] .prog')].some(p => p.textContent !== 'In diretta')`);
await check('scheda Guida TV in fondo ai canali', `!!document.querySelector('.tvcard.act.guide')`);
await check('misure delle schede', SIZES);
await press('down', 'right');
await check('dettaglio del programma scelto', `document.getElementById('detail').classList.contains('show')`);
await shot('home');

console.log('guida TV');
await open('guide');
await check('canali a sinistra', `document.querySelectorAll('#guide-chans .gch').length >= 3`);
await check('programmi a destra', `document.querySelectorAll('#guide-progs .gprog').length >= 2`);
await shot('guida');

console.log('impostazioni');
await open('settings');
await check('quattro gruppi', `document.querySelectorAll('.setcat').length === 4`);
await check('primo gruppo selezionato', `document.activeElement.dataset.go === 'set-av'`);
await press('right', 'right', 'ok');
await check('gruppo Home e meteo', `document.body.dataset.page === 'set-home'`);
await press('ok');
await check('canali in diretta: elenco', `document.querySelectorAll('#channels-list .btn').length >= 20`, 15000);
await shot('canali');
await press('back');
await check('di nuovo nel gruppo Home e meteo', `document.body.dataset.page === 'set-home'`, 4000);
await press('down', 'ok');
await check('riquadri della home: servizi, nessun canale', `(() => { const t = [...document.querySelectorAll('#homeedit-list .btn')].map(b => b.textContent);
  return t.length >= 5 && t.some(x => x.includes('YouTube')) && !t.some(x => /Rai 1|Canale 5/.test(x)); })()`, 6000);
// uno dei tuoi siti nella home: si toglie anche da Riquadri della home
await js(`fetch('/api/sites?action=add&label=Sito%20di%20prova&url=' + encodeURIComponent('https://example.org/'))
  .then(() => fetch('/api/sites?action=home&on=1&url=' + encodeURIComponent('https://example.org/')))`);
await js(`Promise.all([import('/js/home.js'), import('/js/lists.js')]).then(([h, l]) => h.rebuild().then(() => l.homeEditPage()))`);
await check('il tuo sito nella home: elencato', `!!document.querySelector('#homeedit-list [data-hid="sito:https://example.org/"]')`, 6000);
await js(`document.querySelector('#homeedit-list [data-hid="sito:https://example.org/"]').focus()`);
await press('ok', 'ok');
await check('il tuo sito: tolto dalla home', `!document.querySelector('#page-home .bigrow [data-url="https://example.org/"]')
  && !document.querySelector('#homeedit-list [data-hid^="sito:"]')`, 6000);
await js(`fetch('/api/sites?action=remove&url=' + encodeURIComponent('https://example.org/'))`);
// un servizio di Altri servizi messo anche in home (e poi tolto)
await js(`document.querySelector('#homeedit-list [data-hid="la7"]').focus()`);
await press('ok');
await check('La7: scelta "Anche in home"', `document.activeElement.textContent === 'Anche in home'`, 3000);
await press('ok');
await check('La7 tra i riquadri grandi, prima di Altri servizi', `(() => { const ids = [...document.querySelectorAll('#page-home .bigrow .tile')].map(t => t.dataset.id);
  return ids.includes('la7') && ids.indexOf('la7') === ids.indexOf('altri') - 1; })()`, 4000);
await check('La7: segnata "in home e in Altri servizi"', `document.querySelector('#homeedit-list [data-hid="la7"]').textContent.includes('in home')`, 3000);
await press('ok');
await check('La7: scelta "Solo in Altri servizi"', `document.activeElement.textContent === 'Solo in Altri servizi'`, 3000);
await press('ok');
await check('La7 di nuovo solo in Altri servizi', `!document.querySelector('#page-home .bigrow [data-id="la7"]') && !!document.querySelector('#altri-row [data-id="la7"]')`, 4000);

// account discovery+ (nessuna sezione in tvbox): l'accesso si apre da Rete e assistenza
await js(`import('/js/core.js').then(c => c.state.show('set-net'))`);
await check('discovery+: riga account, non collegato', `(() => { const r = document.querySelector('[data-act="account"][data-svc="discovery"]');
  return r && r.querySelector('.aname').textContent === 'Discovery+' && r.querySelector('.val').textContent === 'non collegato'; })()`, 6000);
await js(`document.querySelector('[data-act="account"][data-svc="discovery"]').focus()`);
await press('ok');
await check('discovery+: schermata di accesso (Email, Password, Accedi)', `document.body.dataset.page === 'login'
  && [...document.querySelectorAll('#login-box .lfield .lk')].map(e => e.textContent).join() === 'Email,Password'
  && !!document.querySelector('#login-box .lgo') && document.activeElement.classList.contains('lfield')`, 4000);
await shot('accesso-discovery');
await press('back');
await check('discovery+: MENU torna a Rete e assistenza', `document.body.dataset.page === 'set-net'`, 3000);

console.log('mediaset');
await open('mediaset');
await check('righe di locandine', `document.querySelectorAll('.poster').length >= 10`);
await check('almeno cinque righe (fiction, serie, programmi, cartoni…)', `document.querySelectorAll('.msrail').length >= 5`);
await check('logo o titolo della serie scelta', `!!document.getElementById('ms-name').textContent`);
await check('misure delle locandine', SIZES);
await press('right');
await check('foto della serie sullo sfondo', `document.getElementById('ms-bg').classList.contains('on')`);
await check('logo della serie', `document.getElementById('ms-logo').classList.contains('ok')`);
await sleep(800);
await shot('mediaset');
await press('ok');
await check('pagina della serie con episodi', `document.querySelectorAll('.msep').length >= 1`);
await check('episodio scelto leggibile (fondo bianco)', `getComputedStyle(document.activeElement).backgroundColor === 'rgb(255, 255, 255)'`);
await until(`document.getElementById('mss-logo').classList.contains('ok')`, 8000);
await sleep(1500);
await shot('serie');
await open('mediaset');
await check('locandine di nuovo', `document.activeElement.classList.contains('poster')`);
await press('down', 'down', 'down');
await check('scendendo: riga Cartoni scelta e visibile', `(() => { const r = document.activeElement.closest('.msrail');
  const b = document.activeElement.getBoundingClientRect();
  return r && /Cartoni/i.test(r.querySelector('h2').textContent) && b.top >= 0 && b.bottom <= innerHeight; })()`, 5000);
await sleep(800);
await shot('mediaset-cartoni');

// frecce: barra di ricerca larga e gruppi di pulsanti che vanno a capo (AnimeUnity, senza account)
console.log('frecce');
await js(`fetch('/api/au?action=play&url=' + encodeURIComponent('https://animeunity.cx/anime/12-one-piece/110339') +
  '&series=12-one-piece&title=One%20Piece&episode=110339&n=1180&ep=Episodio%201180').then(r => r.json())`);
await open('au');
await until(`!!document.querySelector('#au-rails .poster')`, 15000);
await js(`document.querySelector('.au-search-field').focus()`);
await press('down');
await check('ricerca ▼: la prima riga (Continua a guardare)', `/Continua/.test(document.activeElement.closest('.msrail')?.querySelector('.sec-title')?.textContent || '')`, 3000);
await js(`document.querySelector('.au-search-field').focus()`);
await press('ok');
await js(`(() => { for (const c of 'naruto') __osk.key(c);
  [...document.getElementById('__osk_host').shadowRoot.querySelectorAll('.key')].find(k => k.textContent === 'FATTO').click(); })()`);
await until(`[...document.querySelectorAll('.au-search .btn')].some(b => b.textContent === 'Cancella')`, 15000);
await js(`document.querySelector('.au-search-field').focus()`);
await press('right');
await check('ricerca ►: il pulsante Cancella', `document.activeElement.textContent === 'Cancella'`, 3000);
await open('au:12-one-piece');
await until(`document.querySelectorAll('#aus-seasons .chip').length > 6`, 20000);
await js(`document.querySelector('#aus-seasons .chip').focus()`);
await press('right', 'right', 'right', 'right');
await check('gruppi di episodi: ► in ordine anche a capo (1–100 → 401–500)', `document.activeElement.textContent === '401–500'`, 3000);

console.log('errori JavaScript:', errors.length ? errors : 'nessuno');
ws.close();
process.exit(failed || errors.length ? 1 : 0);

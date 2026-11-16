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

console.log('mediaset');
await open('mediaset');
await check('righe di locandine', `document.querySelectorAll('.poster').length >= 10`);
await check('logo o titolo della serie scelta', `!!document.getElementById('ms-name').textContent`);
await check('misure delle locandine', SIZES);
await shot('mediaset');
await press('ok');
await check('pagina della serie con episodi', `document.querySelectorAll('.msep').length >= 1`);
await check('episodio scelto leggibile (fondo bianco)', `getComputedStyle(document.activeElement).backgroundColor === 'rgb(255, 255, 255)'`);
await shot('serie');

console.log('errori JavaScript:', errors.length ? errors : 'nessuno');
ws.close();
process.exit(failed || errors.length ? 1 : 0);

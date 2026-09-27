#!/usr/bin/env node
/** Browser application QA via Chromium CDP. This is not an AXIS capability test. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const root = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
function option(name, fallback) {
  const index = args.indexOf(name);
  return index < 0 ? fallback : args[index + 1];
}
const browser = option('--browser', process.env.CHROME_PATH) || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].find(existsSync);
if (!browser) throw new Error('No Chromium executable found. Pass --browser PATH.');
await mkdir(join(root, '.browser-test'), { recursive: true });
const runDir = await mkdtemp(join(root, '.browser-test', 'run-'));
const profile = join(runDir, 'profile');
await mkdir(profile);
const report = { kind: 'Chromium CDP application QA; not AXIS proof', checks: [], errors: [], runDir };
let chrome;
let server;
let cdp;
let browserCdp;
let browserOutput = '';
let serverOutput = '';

async function until(fn, description, timeout = 15000) {
  const deadline = Date.now() + timeout;
  let last;
  while (Date.now() < deadline) {
    try { const value = await fn(); if (value) return value; } catch (error) { last = error; }
    await delay(150);
  }
  throw new Error(`Timed out: ${description}${last ? ` (${last.message})` : ''}`);
}

class Protocol {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    this.events = [];
    socket.addEventListener('message', ({ data }) => {
      const event = JSON.parse(data);
      if (event.id) {
        const pending = this.pending.get(event.id);
        if (!pending) return;
        this.pending.delete(event.id);
        clearTimeout(pending.timer);
        if (event.error) pending.reject(new Error(`${pending.method}: ${event.error.message}`));
        else pending.resolve(event.result);
      } else {
        this.events.push(event);
        if (this.events.length > 1000) this.events.shift();
        if (event.method === 'Runtime.exceptionThrown') {
          report.errors.push(event.params.exceptionDetails.exception?.description || event.params.exceptionDetails.text);
        }
      }
    });
    socket.addEventListener('close', () => {
      for (const pending of this.pending.values()) {
        clearTimeout(pending.timer);
        pending.reject(new Error(`Browser connection closed: ${pending.method}`));
      }
      this.pending.clear();
    });
  }
  static async connect(url) {
    const socket = new WebSocket(url);
    await new Promise((resolve, reject) => {
      socket.addEventListener('open', resolve, { once: true });
      socket.addEventListener('error', reject, { once: true });
    });
    return new Protocol(socket);
  }
  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
      this.pending.set(id, { resolve, reject, timer, method });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
  close() { this.socket.close(); }
}

async function evaluate(expression) {
  const result = await cdp.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result.value;
}
const query = selector => `document.querySelector(${JSON.stringify(selector)})`;
async function wait(expression, description = expression) { return until(() => evaluate(expression), description); }
async function click(selector, scope = 'document') {
  const element = `${scope}.querySelector(${JSON.stringify(selector)})`;
  const box = await evaluate(`(() => {
    const el = ${element}; if (!el) throw new Error('Missing control: ' + ${JSON.stringify(selector)});
    el.scrollIntoView({block:'center',inline:'center'});
    const r = el.getBoundingClientRect();
    const frame = el.ownerDocument.defaultView.frameElement;
    const f = frame ? frame.getBoundingClientRect() : {left:0,top:0};
    return {x:r.left+r.width/2+f.left,y:r.top+r.height/2+f.top,width:r.width,height:r.height,disabled:el.disabled};
  })()`);
  assert.ok(box.width && box.height && !box.disabled, `Control must be visible and enabled: ${selector}`);
  await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y });
  await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: box.x, y: box.y, button: 'left', clickCount: 1 });
  await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: box.x, y: box.y, button: 'left', clickCount: 1 });
}
async function key(key, code, modifiers = 0) {
  const windowsVirtualKeyCode = { a: 65, Backspace: 8, Enter: 13, Escape: 27, Tab: 9, Home: 36, ArrowDown: 40, ArrowRight: 39, ArrowLeft: 37, ' ': 32 }[key] || 0;
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key, code, modifiers, windowsVirtualKeyCode });
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key, code, modifiers, windowsVirtualKeyCode });
}
async function fill(selector, text, scope = 'document') {
  await click(selector, scope);
  await key('a', 'KeyA', 2);
  await key('Backspace', 'Backspace');
  if (text) await cdp.send('Input.insertText', { text });
}
async function choose(selector, value) {
  // Real select keyboard interaction. Only option discovery reads the DOM.
  const index = await evaluate(`Array.from(${query(selector)}.options).findIndex(o => o.value === ${JSON.stringify(value)})`);
  assert.ok(index >= 0, `Select option exists: ${selector}=${value}`);
  await evaluate(`${query(selector)}.focus()`);
  await key('Home', 'Home');
  for (let i = 0; i < index; i++) await key('ArrowDown', 'ArrowDown');
  await key('Enter', 'Enter');
  assert.equal(await evaluate(`${query(selector)}.value`), value);
}
async function check(name, fn) {
  await fn();
  report.checks.push(name);
  console.log(`PASS ${name}`);
}
async function nativeDialog(selector, type, accept, promptText) {
  cdp.events = cdp.events.filter(event => event.method !== 'Page.javascriptDialogOpening');
  const action = click(selector);
  const event = await until(() => cdp.events.find(event => event.method === 'Page.javascriptDialogOpening'), `${type} browser dialog`);
  assert.equal(event.params.type, type);
  await cdp.send('Page.handleJavaScriptDialog', { accept, ...(promptText === undefined ? {} : { promptText }) });
  await action;
}
async function navigate(url) {
  await cdp.send('Page.navigate', { url });
  await wait(`document.readyState === 'complete' && !!document.querySelector('[data-view="customers"]')`, 'application loaded');
}

async function applicationUrl() {
  const supplied = option('--url');
  if (supplied) {
    const url = new URL(supplied);
    assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(url.hostname), 'QA only supports local test servers');
    return url.origin;
  }
  assert.ok(existsSync(join(root, 'server.py')), 'Missing testbench/server.py');
  server = spawn(option('--python', 'python'), ['-u', join(root, 'server.py'), '--port', '0', '--db', join(runDir, 'ops.sqlite3')], {
    cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  });
  server.stdout.on('data', chunk => { serverOutput += chunk.toString(); });
  server.stderr.on('data', chunk => { serverOutput += chunk.toString(); });
  server.on('error', error => { serverOutput += error.message; });
  const port = await until(() => serverOutput.match(/http:\/\/localhost:(\d+)\//)?.[1], 'disposable backend startup');
  const url = `http://127.0.0.1:${port}`;
  await until(async () => {
    if (server.exitCode !== null) throw new Error(`Server exited ${server.exitCode}: ${serverOutput}`);
    return (await fetch(`${url}/api/state`)).ok;
  }, 'disposable backend readiness');
  return url;
}

try {
  chrome = spawn(browser, [
    '--headless=new', '--no-sandbox', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--window-size=1440,1000', 'about:blank',
  ], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
  chrome.stderr.on('data', chunk => { browserOutput += chunk.toString(); });
  chrome.on('error', error => { browserOutput += error.message; });
  const portFile = await until(async () => {
    if (chrome.exitCode !== null) throw new Error(`Chromium exited ${chrome.exitCode}: ${browserOutput}`);
    return readFile(join(profile, 'DevToolsActivePort'), 'utf8');
  }, 'Chromium debugger startup');
  const [port, browserPath] = portFile.trim().split(/\r?\n/);
  browserCdp = await Protocol.connect(`ws://127.0.0.1:${port}${browserPath}`);
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  cdp = await Protocol.connect(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  if (args.includes('--probe')) {
    console.log('PASS disposable headless Chromium + Node WebSocket CDP');
    report.checks.push('disposable Chromium startup and CDP connection');
  } else {
    const url = await applicationUrl();
    report.url = url;
    const api = async path => {
      const response = await fetch(url + path);
      assert.ok(response.ok, `${path}: HTTP ${response.status}`);
      return response.json();
    };
    const state = () => api('/api/state');
    const original = await state();
    const customer = original.customers.find(item => item.id === 1);
    const duplicate = original.customers.find(item => item.id !== 1);
    assert.ok(customer && duplicate, 'Seed customer fixtures are present');
    const view = async name => {
      await click(`[data-view="${name}"]`);
      await wait(`document.querySelector('[data-view="${name}"]').getAttribute('aria-current') === 'page' || document.querySelector('[data-view="${name}"]').classList.contains('active')`, `${name} view active`);
    };
    const saved = (predicate, description) => until(async () => predicate(await state()), description);
    const screenshot = async filename => {
      const result = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
      await writeFile(join(runDir, filename), Buffer.from(result.data, 'base64'));
    };
    await check('default page opens the CAPTCHA training ground', async () => {
      await navigate(url);
      await wait(`document.querySelector('[data-view="captchas"]')?.getAttribute('aria-current') === 'page'`, 'CAPTCHA view is the default');
      await wait(`document.querySelectorAll('#captcha-training [data-captcha]').length === 4`, 'four local challenges mounted');
      assert.equal(await evaluate(`${query('#view-captchas')}.hidden`), false);
      await screenshot('captcha-training.png');
    });

    await check('local canvas challenges reject wrong answers and regenerate', async () => {
      for (const kind of ['jigsaw', 'tiles', 'text', 'rotation']) {
        const card = `#captcha-training [data-captcha="${kind}"]`;
        const before = await evaluate(`${query(card + ' canvas')}.toDataURL()`);
        if (kind === 'text') {
          await fill(`${card} input[type="text"]`, 'BAD');
          await key('Enter', 'Enter');
        } else {
          if (kind !== 'tiles') {
            await click(`${card} input[type="range"]`);
            await key('Home', 'Home');
          }
          await click(`${card} [data-action="verify"]`);
        }
        await wait(`${query(card + ' .captcha-feedback')}.classList.contains('failed')`, `${kind} rejects incorrect answer`);
        assert.equal(await evaluate(`${query(card + ' .captcha-feedback')}.classList.contains('passed')`), false);
        await click(`${card} [data-action="refresh"]`);
        assert.equal(await evaluate(`${query(card + ' .captcha-feedback')}.classList.contains('failed')`), false);
        assert.notEqual(await evaluate(`${query(card + ' canvas')}.toDataURL()`), before, `${kind} generates a fresh image`);
        if (kind === 'text') assert.equal(await evaluate(`${query(card + ' input')}.value`), '');
        if (kind === 'jigsaw' || kind === 'rotation') {
          assert.equal(await evaluate(`${query(card + ' input')}.value`), '0');
          await click(`${card} input`);
          await key('Home', 'Home');
          await key('ArrowRight', 'ArrowRight');
          assert.ok(Number(await evaluate(`${query(card + ' input')}.value`)) > 0, 'Native range supports keyboard adjustment');
        }
      }
    });

    await check('image tile selection supports mouse, keyboard, and reset', async () => {
      const tile = '#captcha-training [data-captcha="tiles"] .captcha-tile';
      await click(tile);
      assert.equal(await evaluate(`${query(tile)}.getAttribute('aria-pressed')`), 'true');
      await key(' ', 'Space');
      assert.equal(await evaluate(`${query(tile)}.getAttribute('aria-pressed')`), 'false');
      await click(tile);
      await click('#captcha-training [data-captcha="tiles"] [data-action="refresh"]');
      assert.equal(await evaluate(`document.querySelectorAll('#captcha-training .captcha-tile[aria-pressed="true"]').length`), 0);
    });

    await check('unavailable Cloudflare script cannot produce provider success', async () => {
      assert.equal(await evaluate(`${query('#verify-turnstile')}.disabled`), true);
      assert.match(await evaluate(`${query('#provider-mode')}.textContent`), /test mode/i);
      await cdp.send('Network.enable');
      await cdp.send('Network.setBlockedURLs', { urls: ['*://challenges.cloudflare.com/*'] });
      try {
        await click('#load-turnstile');
        await wait(`${query('#turnstile-status')}.textContent.includes('could not load')`, 'provider reports an actual script load failure');
        assert.equal(await evaluate(`${query('#verify-turnstile')}.disabled`), true);
        assert.equal(await evaluate(`${query('#load-turnstile')}.disabled`), false);
        assert.equal(await evaluate(`!!window.turnstile`), false);
        report.providerOnlineVerification = 'Not exercised; deterministic unavailable-script behavior verified.';
      } finally { await cdp.send('Network.setBlockedURLs', { urls: [] }); }
    });

    await navigate(url + '/#customers');
    await wait(`!!document.querySelector('[data-edit-customer]')`, 'customer records rendered');
    await fill('#customer-search', 'maya');
    await wait(`!!document.querySelector('[data-edit-customer="1"]')`, 'Maya search result');

    await check('native customer dialog: validation, Escape, focus restoration', async () => {
      await click('[data-edit-customer="1"]');
      assert.equal(await evaluate(`${query('#customer-dialog')} instanceof HTMLDialogElement && ${query('#customer-dialog')}.open`), true);
      for (let i = 0; i < 10; i++) {
        await key('Tab', 'Tab');
        assert.equal(await evaluate(`${query('#customer-dialog')}.contains(document.activeElement)`), true, 'Tab focus stays within modal');
      }
      await fill('#customer-form [name="name"]', '');
      await click('#customer-form button[type="submit"]');
      assert.equal(await evaluate(`${query('#customer-dialog')}.open && !${query('#customer-form [name="name"]')}.validity.valid`), true);
      assert.equal((await state()).customers.find(item => item.id === 1).name, customer.name);
      await fill('#customer-form [name="name"]', 'Maya Chén');
      await fill('#customer-form [name="email"]', 'invalid-address');
      await click('#customer-form button[type="submit"]');
      assert.equal(await evaluate(`${query('#customer-dialog')}.open && ${query('#customer-form [name="email"]')}.validity.typeMismatch`), true);
      await key('Escape', 'Escape');
      await wait(`!${query('#customer-dialog')}.open`, 'Escape closes native dialog');
      assert.equal(await evaluate(`document.activeElement === ${query('[data-edit-customer="1"]')}`), true);
    });

    await check('server duplicate-email conflict is displayed without closing dialog', async () => {
      await click('[data-edit-customer="1"]');
      await fill('#customer-form [name="email"]', duplicate.email);
      await click('#customer-form button[type="submit"]');
      await wait(`!!document.querySelector('#customer-dialog [role="alert"]')?.textContent.trim()`, 'customer API error displayed');
      assert.equal(await evaluate(`${query('#customer-dialog')}.open`), true);
      assert.equal((await state()).customers.find(item => item.id === 1).email, customer.email);
      assert.match(await evaluate(`${query('#customer-dialog [role="alert"]')}.textContent`), /already|duplicate|used|exists/i);
    });

    await check('customer save persists Unicode and survives browser reload', async () => {
      await fill('#customer-form [name="name"]', 'Maya Chén');
      await fill('#customer-form [name="email"]', 'maya.chen+ops@example.test');
      await choose('#customer-form [name="plan"]', 'Team');
      await click('#customer-form button[type="submit"]');
      await wait(`!${query('#customer-dialog')}.open`, 'customer save closes dialog');
      await saved(s => s.customers.some(item => item.id === 1 && item.name === 'Maya Chén' && item.plan === 'Team' && item.email === 'maya.chen+ops@example.test'), 'saved customer state');
      await navigate(url + '/#customers');
      await wait(`!!document.querySelector('[data-edit-customer]')`, 'customer list after reload');
      await fill('#customer-search', 'maya');
      await wait(`document.body.innerText.includes('Maya Chén')`, 'persisted customer after reload');
      await screenshot('customers.png');
    });

    await check('customer pagination uses distinct pages and restores previous records', async () => {
      await fill('#customer-search', '');
      const first = await evaluate(`Array.from(document.querySelectorAll('[data-edit-customer]'), el => el.dataset.editCustomer)`);
      await click('#next-page');
      await wait(`document.querySelector('#customer-page-info').textContent.includes('Page 2')`, 'next page displays different records');
      const second = await evaluate(`Array.from(document.querySelectorAll('[data-edit-customer]'), el => el.dataset.editCustomer)`);
      assert.ok(second.length && second.every(id => !first.includes(id)), 'Customer pages do not overlap');
      await click('#previous-page');
      await wait(`document.querySelector('#customer-page-info').textContent.includes('Page 1')`, 'previous customer page restored');
      assert.deepEqual(await evaluate(`Array.from(document.querySelectorAll('[data-edit-customer]'), el => el.dataset.editCustomer)`), first);
    });

    await check('customer search filters and exposes an empty result', async () => {
      await fill('#customer-search', 'no-customer-qa-777');
      await wait(`document.querySelectorAll('[data-edit-customer]').length === 0`, 'search removes unmatched rows');
      assert.match(await evaluate('document.body.innerText'), /no (customers|matching|results)|0 (customers|results)|nothing found/i);
      await fill('#customer-search', 'maya.chen+ops@example.test');
      await wait(`document.querySelectorAll('[data-edit-customer]').length === 1 && !!document.querySelector('[data-edit-customer="1"]')`, 'search finds saved customer');
      await fill('#customer-search', '');
    });

    await check('ticket edit persists priority, assignee, and status', async () => {
      await view('tickets');
      await click('[data-edit-ticket="AX-104"]');
      await choose('#ticket-form [name="priority"]', 'High');
      await choose('#ticket-form [name="assignee"]', 'Maya Chen');
      await choose('#ticket-form [name="status"]', 'Done');
      await click('#ticket-form button[type="submit"]');
      await wait(`!${query('#ticket-dialog')}.open`, 'ticket dialog saved');
      await saved(s => s.tickets.some(item => item.id === 'AX-104' && item.priority === 'High' && item.assignee === 'Maya Chen' && item.status === 'Done'), 'persisted ticket update');
    });

    await check('synthetic HTML drag fixture persists ticket movement', async () => {
      // This exercises the app's HTML Drag and Drop handlers, not AXIS pointer kinematics.
      for (const lane of ['Backlog', 'Done']) {
        await evaluate(`(() => {
          const card = document.querySelector('[data-ticket-id="AX-104"]');
          const lane = document.querySelector('[data-lane="${lane}"]');
          const dataTransfer = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {bubbles:true,dataTransfer}));
          lane.dispatchEvent(new DragEvent('dragover', {bubbles:true,cancelable:true,dataTransfer}));
          lane.dispatchEvent(new DragEvent('drop', {bubbles:true,cancelable:true,dataTransfer}));
          card.dispatchEvent(new DragEvent('dragend', {bubbles:true,dataTransfer}));
        })()`);
        await saved(s => s.tickets.some(item => item.id === 'AX-104' && item.status === lane), `ticket moved to ${lane}`);
        await wait(`!!document.querySelector('[data-lane="${lane}"] [data-ticket-id="AX-104"]')`, 'ticket DOM reflects server status');
      }
      await screenshot('tickets.png');
    });

    await check('native pointer drag moves a ticket across board lanes', async () => {
      await evaluate(`window.qaDragEvents=[]; for(const type of ['dragstart','dragenter','drop','dragend'])document.addEventListener(type,event=>window.qaDragEvents.push({type,target:event.target.dataset.ticketId||event.target.dataset.lane||event.target.tagName,data:event.dataTransfer?.getData('text/plain')}),true)`);
      for (const target of ['Backlog', 'Done']) {
        const points = await evaluate(`(() => {
          const card = document.querySelector('[data-ticket-id="AX-104"]');
          card.scrollIntoView({block:'center'});
          const start = card.getBoundingClientRect();
          const lane = document.querySelector('[data-lane="${target}"]').getBoundingClientRect();
          return {sx:start.left+10,sy:start.top+10,ex:lane.right-20,ey:start.top+10};
        })()`);
        await cdp.send('Input.dispatchMouseEvent', {type:'mouseMoved',x:points.sx,y:points.sy});
        await cdp.send('Input.dispatchMouseEvent', {type:'mousePressed',x:points.sx,y:points.sy,button:'left',buttons:1,clickCount:1});
        for(let step=1;step<=15;step++) {
          await cdp.send('Input.dispatchMouseEvent', {type:'mouseMoved',x:points.sx+(points.ex-points.sx)*step/15,y:points.sy+(points.ey-points.sy)*step/15,button:'left',buttons:1});
          await delay(25);
        }
        // Chromium needs a move after entering the final child to dispatch dragover.
        await cdp.send('Input.dispatchMouseEvent', {type:'mouseMoved',x:points.ex,y:points.ey,button:'left',buttons:1});
        await cdp.send('Input.dispatchMouseEvent', {type:'mouseMoved',x:points.ex,y:points.ey,button:'left',buttons:1});
        await cdp.send('Input.dispatchMouseEvent', {type:'mouseReleased',x:points.ex,y:points.ey,button:'left',clickCount:1});
        report.dragAttempts ||= [];
        report.dragAttempts.push({target,points,events:await evaluate('window.qaDragEvents')});
        await saved(s => s.tickets.some(item => item.id === 'AX-104' && item.status === target), `native drag to ${target}`);
        await wait(`!!document.querySelector('[data-lane="${target}"] [data-ticket-id="AX-104"]')`, 'native drop rendered');
      }
    });

    await check('real file bytes upload and browser download round trip (CDP file selection)', async () => {
      await view('documents');
      const filename = join(runDir, 'contacts.csv');
      const bytes = Buffer.from('name,email\r\n"Maya Chén",maya.chen@example.test\r\n"Alex Morgan",alex.morgan@example.test\r\n', 'utf8');
      await writeFile(filename, bytes);
      const { root: document } = await cdp.send('DOM.getDocument');
      const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: document.nodeId, selector: '#file-upload' });
      assert.ok(nodeId, 'Native file input exists');
      await cdp.send('DOM.setFileInputFiles', { nodeId, files: [filename] });
      const uploaded = await until(async () => (await state()).documents.find(item => item.name === 'contacts.csv'), 'uploaded document');
      const downloadSelector = `a[href="/api/documents/${uploaded.id}"]`;
      await wait(`!!${query(downloadSelector)}`, 'document download link');
      const downloads = join(runDir, 'downloads');
      await mkdir(downloads);
      await browserCdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: downloads });
      await click(downloadSelector);
      const downloaded = await until(async () => {
        const names = await readdir(downloads);
        const found = names.find(name => name.endsWith('.csv'));
        return found ? readFile(join(downloads, found)) : null;
      }, 'completed browser file download');
      assert.deepEqual(downloaded, bytes);
      assert.equal(uploaded.size, bytes.length);
      const response = await fetch(`${url}/api/documents/${uploaded.id}`);
      assert.match(response.headers.get('content-disposition'), /attachment/i);
      assert.deepEqual(Buffer.from(await response.arrayBuffer()), bytes);
      await screenshot('documents.png');
    });

    await check('embedded iframe requires confirmation and persists purchase approval', async () => {
      await view('approvals');
      const frame = `${query('#approval-frame')}.contentDocument`;
      await wait(`!!${frame}?.querySelector('#approve-order') && !${frame}.querySelector('#approval-controls').disabled`, 'iframe controls ready');
      await click('#approve-order', frame);
      assert.equal((await state()).approval.status, 'Pending');
      assert.equal(await evaluate(`${frame}.querySelector('#confirm-approval').validity.valueMissing`), true);
      await click('#confirm-approval', frame);
      await click('#approve-order', frame);
      await saved(s => s.approval.status === 'Approved', 'purchase approval persisted');
      await wait(`${frame}.querySelector('#order-status').textContent === 'Approved'`, 'iframe approval display');
    });

    await check('shadow DOM editor persists multiline Unicode note and reloads', async () => {
      const editor = `${query('ops-note-editor')}.shadowRoot`;
      const note = 'Approved for September rollout\nHandover: Élodie — Brussels ✓';
      await wait(`!!${editor}?.querySelector('#note-body')`, 'shadow editor available');
      await fill('#note-body', note, editor);
      assert.equal(await evaluate(`${query('ops-note-editor')}.value`), note);
      await click('#save-note');
      await saved(s => s.note.text === note, 'persisted note bytes');
      await wait(`document.querySelector('#note-status').textContent === 'Note saved.' && document.querySelector('#save-note').disabled`, 'note save acknowledged by UI');
      await navigate(url + '/#customers');
      await view('approvals');
      await wait(`${query('ops-note-editor')}.value === ${JSON.stringify(note)}`, 'note restored after reload');
      await wait(`${query('#approval-frame')}.contentDocument?.querySelector('#order-status')?.textContent === 'Approved'`, 'approval restored after reload');
      await screenshot('approvals.png');
    });

    await check('results reflect persisted business outcomes and export a real attachment', async () => {
      await view('results');
      const current = await state();
      assert.equal(current.results.length, 4);
      assert.deepEqual(current.results.filter(result => !result.passed), []);
      assert.ok(current.events.length >= 5, 'Audit events record mutations');
      const href = await evaluate(`${query('#export-results')}.getAttribute('href')`);
      const response = await fetch(new URL(href, url));
      assert.match(response.headers.get('content-disposition'), /attachment/i);
      const exported = await response.json();
      assert.deepEqual(exported.results, current.results);
      assert.equal(exported.run_id, current.run_id);
      await screenshot('results.png');
    });

    await check('reset confirmation cancels safely and starts a clean persisted run', async () => {
      const previous = await state();
      await click('#reset-run');
      await wait(`${query('#reset-dialog')}.open`, 'reset confirmation open');
      await key('Escape', 'Escape');
      assert.equal((await state()).run_id, previous.run_id);
      await click('#reset-run');
      await click('#confirm-reset');
      await saved(s => s.run_id !== previous.run_id && s.documents.length === 0 && s.approval.status === 'Pending' && s.note.text === '' && s.results.every(result => !result.passed), 'reset persisted state');
      await wait(`!${query('#reset-dialog')}.open`, 'reset dialog closed');
    });
    await check('narrow viewport keeps navigation and work areas within the page', async () => {
      await cdp.send('Emulation.setDeviceMetricsOverride', {width:390,height:844,deviceScaleFactor:1,mobile:false});
      for(const name of ['customers','tickets','documents','approvals','results']) {
        await view(name);
        const layout = await evaluate(`({width:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll('body *')].filter(el=>el.getBoundingClientRect().right>391 && !el.closest('.table-scroll,nav')).map(el=>({tag:el.tagName,id:el.id,class:el.className,right:el.getBoundingClientRect().right})).slice(0,8)})`);
        assert.ok(layout.width <= 391, `${name} fits narrow viewport: ${JSON.stringify(layout)}`);
        await screenshot(`mobile-${name}.png`);
      }
    });
    assert.deepEqual(report.errors, [], 'No uncaught browser JavaScript exceptions');
    console.log(`${report.checks.length} browser application checks passed. AXIS desktop interaction was not tested by this runner.`);
  }
} catch (error) {
  report.failure = error.stack || String(error);
  console.error(report.failure);
  process.exitCode = 1;
} finally {
  if (cdp) {
    try {
      const screenshot = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
      await writeFile(join(runDir, 'browser.png'), Buffer.from(screenshot.data, 'base64'));
    } catch { /* Browser startup failures have no screenshot. */ }
  }
  await writeFile(join(runDir, 'report.json'), JSON.stringify(report, null, 2));
  await writeFile(join(runDir, 'chromium.log'), browserOutput);
  if (serverOutput) await writeFile(join(runDir, 'server.log'), serverOutput);
  try { await browserCdp?.send('Browser.close'); } catch { /* Browser may already be closed. */ }
  cdp?.close();
  browserCdp?.close();
  if (chrome && chrome.exitCode === null) chrome.kill();
  if (server && server.exitCode === null) server.kill();
  // Only remove the disposable profile created by this invocation; retain screenshots and reports.
  const relativeProfile = relative(resolve(root), resolve(profile));
  assert.ok(relativeProfile.startsWith(`.browser-test${sep}run-`) && resolve(profile).startsWith(resolve(runDir) + sep));
  try { await rm(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }); } catch { /* Chromium can briefly retain profile handles. */ }
  console.log(`Application QA artifacts: ${runDir}`);
}

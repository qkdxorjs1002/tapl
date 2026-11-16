const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { mkdtempSync, realpathSync, rmSync, mkdirSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { chromium } = require('@playwright/test');
const { version } = require('../../package.json');
const root = path.resolve(__dirname, '../../..');
const workspace = realpathSync(mkdtempSync(path.join(tmpdir(), 'tapl-version-')));
const api = 'https://api.github.com/repos/qkdxorjs1002/tapl/releases/latest';
let server, browser, origin;

before(async () => {
  server = spawn(process.env.TAPL_PYTHON || path.join(root, 'tapl/.venv/bin/python'),
    [path.join(root, 'vscode-extension/tests/fixtures/workbench.py'), '--workspace', workspace, '--port', '0'],
    {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
  origin = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Viewer startup timed out')), 15000);
    server.once('error', reject); server.once('exit', code => reject(new Error(`Viewer exited: ${code}`)));
    server.stdout.on('data', chunk => {const match = String(chunk).match(/tapl viewer: (http:\/\/\S+)/); if (match) {clearTimeout(timer); resolve(match[1]);}});
    server.stderr.on('data', chunk => process.stderr.write(chunk));
  });
  browser = await chromium.launch(process.env.CHROME_PATH ? {executablePath: process.env.CHROME_PATH} : {channel: 'chrome'});
});
after(async () => {
  await browser?.close();
  if (server && server.exitCode === null) {const done = new Promise(resolve => server.once('exit', resolve)); server.kill(); await done;}
  rmSync(workspace, {recursive: true, force: true});
});
async function fixture({tag = version, ...options} = {}) {
  const page = await browser.newPage({viewport: {width: 1440, height: 900}, locale: 'ko-KR', ...options});
  page.setDefaultTimeout(6000);
  const errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route(api, route => {
    requests.push(route.request());
    return route.fulfill({json: {tag_name: tag, draft: false, prerelease: false, html_url: 'https://evil.example'}});
  });
  return {page, errors, requests};
}
async function bounds(page) {
  const footer = page.locator('.tapl-viewer-version');
  await footer.waitFor();
  const box = await footer.boundingBox(), viewport = page.viewportSize();
  assert.ok(Math.abs(box.x + box.width / 2 - viewport.width / 2) < 1, 'centered in the viewport');
  assert.ok(box.y + box.height <= viewport.height && viewport.height - box.y - box.height <= 8, 'near the viewport bottom');
  assert.ok(box.height <= 24 && box.width < 220, 'small enough to leave neighboring controls accessible');
  const points = await footer.locator('a').evaluateAll(links => links.map(link => {const r = link.getBoundingClientRect(); return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.closest('a') === link;}));
  assert.ok(points.every(Boolean), 'every visible version remains clickable');
}
async function shot(page, name) {
  if (!process.env.TAPL_SCREENSHOT_DIR) return;
  mkdirSync(process.env.TAPL_SCREENSHOT_DIR, {recursive: true});
  await page.screenshot({path: path.join(process.env.TAPL_SCREENSHOT_DIR, `${name}.png`)});
}

test('current bundle version stays small and centered during loading, normal pages, settings and errors', async () => {
  const {page, errors} = await fixture();
  let ready;
  const hold = new Promise(resolve => {ready = resolve;});
  await page.route('**/api/message', async route => {await hold; await route.continue();});
  try {
    await page.goto(origin);
    await bounds(page);
    assert.equal(await page.locator('.tapl-viewer-version a').innerText(), `v${version}`);
    assert.equal(await page.locator('.tapl-viewer-version').getAttribute('data-update'), 'false');
    ready(); await page.unroute('**/api/message');
    await page.locator('.wb-run-mindmap').waitFor();
    await page.locator('[data-wb-focus="nav:settings"]').click();
    await page.locator('.wb-settings-savebar').waitFor(); await bounds(page);
    await page.locator('.wb-settings').evaluate(element => {
      let parent = element.parentElement;
      while (parent && parent.scrollHeight <= parent.clientHeight) parent = parent.parentElement;
      if (parent) parent.scrollTop = parent.scrollHeight;
    });
    await bounds(page);
    await page.locator('.wb-back-layer .wb-back').click();
    await page.evaluate(() => window.postMessage({type: 'error', message: 'Viewer test error', locale: 'ko'}, '*'));
    await page.getByText('Viewer test error').waitFor(); await bounds(page);
    assert.deepEqual(errors, []);
  } finally {ready(); await page.close();}
});

test('new stable release has a subtle ambient highlight and opens its exact fixed GitHub release URL', async () => {
  const {page, errors, requests} = await fixture({tag: 'v99.0.0'});
  try {
    await page.context().route('https://github.com/**', route => route.fulfill({body: 'Release page'}));
    await page.goto(origin);
    const footer = page.locator('.tapl-viewer-version[data-update=true]'); await footer.waitFor();
    assert.equal(await footer.locator('.tapl-viewer-version-current').innerText(), `v${version}`);
    assert.equal(await footer.locator('.tapl-viewer-version-latest').innerText(), 'v99.0.0');
    assert.match(await footer.locator('.tapl-viewer-version-latest').getAttribute('aria-label'), /새 버전/);
    assert.equal(await footer.locator('.tapl-viewer-version-current').getAttribute('href'), `https://github.com/qkdxorjs1002/tapl/releases/tag/${version}`);
    assert.equal(requests.length, 1); assert.equal(requests[0].headers().authorization, undefined);
    for (const theme of ['dark', 'light']) {
      await page.evaluate(theme => document.documentElement.setAttribute('data-tapl-theme', theme), theme);
      for (const width of [1440, 390]) {
        await page.setViewportSize({width, height: width === 390 ? 844 : 900});
        await bounds(page);
        const motion = await footer.locator('.tapl-viewer-version-pill').evaluate(pill => getComputedStyle(pill, '::before').animationDuration);
        assert.equal(motion, '12s');
        await shot(page, `viewer-version-${theme}-${width}`);
      }
    }
    const [popup] = await Promise.all([page.waitForEvent('popup'), footer.locator('.tapl-viewer-version-latest').click()]);
    await popup.waitForLoadState();
    assert.equal(popup.url(), 'https://github.com/qkdxorjs1002/tapl/releases/tag/v99.0.0');
    assert.equal(await popup.evaluate(() => window.opener === null), true);
    await popup.close(); assert.deepEqual(errors, []);
  } finally {await page.close();}
});

test('reduced motion keeps the glow static and native VS Code adapter shows the same build version', async () => {
  const {page, errors} = await fixture({tag: '99.0.0', reducedMotion: 'reduce'});
  await page.addInitScript(() => {
    window.acquireVsCodeApi = () => ({getState: () => undefined, setState() {}, postMessage(message) {
      if (message.command === 'ready') window.postMessage({type: 'hydrate', locale: 'ko', layout: 'auto', view: {type: 'error', message: 'Native host fixture'}}, '*');
    }});
  });
  try {
    await page.goto(origin); await page.getByText('Native host fixture').waitFor();
    const footer = page.locator('.tapl-viewer-version[data-update=true]'); await footer.waitFor(); await bounds(page);
    assert.equal(await footer.locator('.tapl-viewer-version-pill').evaluate(pill => getComputedStyle(pill, '::before').animationName), 'none');
    await shot(page, 'viewer-version-native-reduced-motion'); assert.deepEqual(errors, []);
  } finally {await page.close();}
});

test('hidden pages defer checks, visible unfocused pages check immediately, and reloads reuse the cache', async () => {
  const {page, errors, requests} = await fixture({tag: '99.0.0'});
  await page.addInitScript(() => {
    Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'});
    Object.defineProperty(document, 'hasFocus', {configurable: true, value: () => false});
  });
  try {
    await page.goto(origin); await page.locator('.tapl-viewer-version').waitFor();
    assert.equal(requests.length, 0);
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'visible'});
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await page.locator('.tapl-viewer-version[data-update=true]').waitFor(); assert.equal(requests.length, 1);
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange'))); assert.equal(requests.length, 1);
    await page.reload(); await page.locator('.tapl-viewer-version[data-update=true]').waitFor(); assert.equal(requests.length, 1);
    assert.deepEqual(errors, []);
  } finally {await page.close();}
});

test('offline release checks preserve the current version link without an update decoration', async () => {
  const {page, errors} = await fixture();
  await page.unroute(api); await page.route(api, route => route.abort('internetdisconnected'));
  try {
    await page.goto(origin); await bounds(page);
    const footer = page.locator('.tapl-viewer-version');
    assert.equal(await footer.getAttribute('data-update'), 'false');
    assert.equal(await footer.locator('a').getAttribute('href'), `https://github.com/qkdxorjs1002/tapl/releases/tag/${version}`);
    assert.deepEqual(errors, []);
  } finally {await page.close();}
});

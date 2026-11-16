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

const luminance = color => color.slice(0, 3).map(value => value / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05);

test('native appearance switches only TAPL while following live VS Code palette colors', async () => {
  const {page, errors} = await fixture({reducedMotion: 'reduce'});
  await page.addInitScript(() => {
    window.__nativeCommands = [];
    window.__applyHostTheme = mode => {
      sessionStorage.setItem('native-theme-mode', mode);
      document.body.className = mode;
      const light = mode === 'vscode-light' || mode === 'vscode-high-contrast-light';
      const values = {
        'sideBar-background': light ? '#fff8e9' : '#102438',
        'panel-background': light ? '#fcf5e8' : '#15293d',
        'editor-background': light ? '#fff8e9' : '#102438',
        'editorWidget-background': light ? '#fffdf6' : '#22394e',
        'editor-foreground': light ? '#3c2850' : '#f0ead2',
        'descriptionForeground': light ? '#6d606e' : '#a4b3c5',
        'editor-border': light ? '#9f8260' : '#4d7b9e',
        'input-border': light ? '#8e704d' : '#547694',
        'editorWidget-border': light ? '#84653f' : '#60829f',
        'input-background': light ? '#ede5df' : '#263d53',
        'input-foreground': light ? '#3b2a42' : '#eaf2ff',
        'focusBorder': light ? '#74419c' : '#e5a36d',
        'textLink-foreground': light ? '#704398' : '#7bbfff',
        'textLink-activeForeground': light ? '#653a8d' : '#91cfff',
        'button-background': light ? '#684386' : '#27618c',
        'button-foreground': '#ffffff',
        'button-hoverBackground': light ? '#795397' : '#39739e',
        'button-secondaryBackground': light ? '#e5d7e5' : '#304359',
        'button-secondaryForeground': light ? '#4c3152' : '#eef2f7',
        'button-secondaryHoverBackground': light ? '#d3c5d3' : '#405369',
        'textCodeBlock-background': light ? '#e6dcd4' : '#0b1421',
        'editorHoverWidget-background': light ? '#f9e8d8' : '#283f58',
        'editorHoverWidget-foreground': light ? '#3e2434' : '#edf7ff',
        'editorHoverWidget-border': light ? '#526b87' : '#9eabba',
        'editorInfo-foreground': light ? '#285ead' : '#74bfff',
        'testing-iconPassed': light ? '#247447' : '#8ad8ac',
        'errorForeground': light ? '#a63c36' : '#f5a28a',
        'editorWarning-foreground': light ? '#9b6b16' : '#ffd075',
        'testing-iconSkipped': light ? '#7d4892' : '#ceafea',
        'charts-purple': light ? '#764896' : '#cfa0ea',
        'charts-orange': light ? '#9b6616' : '#eab17b',
        'contrastBorder': light ? '#674fbe' : '#ffe066'
      };
      for (const [key, value] of Object.entries(values)) document.body.style.setProperty(`--vscode-${key}`, value);
    };
    window.acquireVsCodeApi = () => ({
      getState: () => JSON.parse(sessionStorage.getItem('native-theme-state') || '{"workbench":{"version":1}}'),
      setState(value) { sessionStorage.setItem('native-theme-state', JSON.stringify(value)); },
      async postMessage(message) {
        window.__nativeCommands.push(message);
        // Tripwire: an old/global theme message would visibly mutate the mock editor.
        if (message.command === 'toggleTheme') {
          window.__applyHostTheme(document.body.classList.contains('vscode-dark') ? 'vscode-light' : 'vscode-dark');
          return;
        }
        if (message.command === 'ready') window.__applyHostTheme(sessionStorage.getItem('native-theme-mode') || 'vscode-dark');
        const response = await fetch('/api/message', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(message)});
        const payload = await response.json(); payload.locale = 'ko'; window.__lastNativeView = payload;
        window.postMessage(payload, '*');
      }
    });
  });
  const nativeState = () => page.evaluate(() => ({classes: document.body.className, variables: document.body.style.cssText,
    commands: window.__nativeCommands.map(message => message.command)}));
  const colors = () => page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
    const context = canvas.getContext('2d'), probe = document.createElement('span');
    probe.style.position = 'absolute'; probe.style.visibility = 'hidden'; document.body.append(probe);
    const rgba = color => {context.clearRect(0, 0, 1, 1); context.fillStyle = color; context.fillRect(0, 0, 1, 1); return [...context.getImageData(0, 0, 1, 1).data];};
    const names = ['page-bg', 'foreground', 'muted', 'panel', 'surface', 'surface-muted', 'input-content', 'primary', 'primary-content', 'primary-hover', 'secondary', 'secondary-content',
      'tooltip-bg', 'tooltip-content', 'code-bg', 'highlight', 'focus', 'border', 'border-control', 'border-panel', 'success', 'warning', 'error', 'info', 'skipped', 'reference-memory', 'reference-history'];
    const result = {};
    for (const name of names) {probe.style.color = `var(--tapl-${name})`; result[name] = rgba(getComputedStyle(probe).color);}
    result.map = rgba(getComputedStyle(document.querySelector('.wb-run-mindmap')).backgroundColor);
    result.topbarBorder = rgba(getComputedStyle(document.querySelector('.wb-topbar')).borderBottomColor);
    result.scheme = getComputedStyle(document.body).colorScheme;
    result.hostMode = document.body.className;
    probe.remove(); return result;
  });
  const appearance = async (tone) => {
    await page.waitForFunction(value => document.documentElement.dataset.taplNativeTone === value, tone);
    const result = await colors();
    assert.equal(await page.locator('html').getAttribute('data-tapl-theme'), null, 'native appearance never selects the fixed web palette');
    assert.equal(result.scheme, tone);
    assert.ok(tone === 'light' ? luminance(result.map) > .6 : luminance(result.map) < .15, `visible ${tone} canvas`);
    for (const [fg, bg] of [['foreground','page-bg'], ['muted','page-bg'], ['input-content','surface-muted'], ['secondary-content','secondary'], ['tooltip-content','tooltip-bg'], ['primary-content','primary']])
      assert.ok(contrast(result[fg], result[bg]) >= 4.5, `${tone} ${fg}/${bg} contrast: ${contrast(result[fg], result[bg])}`);
    const hostLight = result.hostMode === 'vscode-light' || result.hostMode === 'vscode-high-contrast-light';
    if ((tone === 'light') !== hostLight) {
      for (const name of ['highlight','success','warning','error','info','skipped','reference-memory','reference-history'])
        assert.ok(contrast(result[name], result.panel) >= 4.5, `${tone} semantic ${name} contrast`);
      assert.ok(contrast(result.focus, result['page-bg']) >= 3, `${tone} focus contrast`);
    }
    return result;
  };
  const toggleLocal = async tone => {
    const before = await nativeState(); await page.locator('[data-wb-focus="theme-toggle"]').click();
    assert.deepEqual(await nativeState(), before, 'no host class, variables or commands change'); return appearance(tone);
  };
  try {
    await page.goto(origin); await page.locator('.wb-run-mindmap').waitFor();
    await page.waitForFunction(() => document.body.classList.contains('vscode-dark'));
    const original = await colors(); assert.deepEqual(original.map, [16,36,56,255]);
    assert.equal(await page.locator('html').getAttribute('data-tapl-native-tone'), null, 'initial appearance follows the host');
    const light = await toggleLocal('light');
    for (const role of ['primary','primary-content','primary-hover']) assert.deepEqual(light[role], original[role], `native ${role} stays intact`);
    assert.ok(light.highlight[2] > light.highlight[0], 'host blue accent retains its hue');
    await shot(page, 'tapl-local-light-vscode-dark');
    await page.evaluate(() => {
      document.body.style.setProperty('--vscode-sideBar-background', '#341a36');
      document.body.style.setProperty('--vscode-textLink-foreground', '#f28fce');
    });
    const pink = await appearance('light');
    assert.notDeepEqual(pink.map, light.map, 'live host colors update the local light surface');
    assert.ok(pink.highlight[0] > pink.highlight[2] && pink.highlight[2] > pink.highlight[1], 'new host pink accent remains pink');
    await page.reload(); await page.locator('.wb-run-mindmap').waitFor(); await appearance('light');
    assert.equal(await page.evaluate(() => JSON.parse(sessionStorage.getItem('native-theme-state')).workbench.theme), 'light', 'local preference survives reload');
    await page.evaluate(() => window.__applyHostTheme('vscode-light'));
    const matchingLight = await appearance('light'); assert.deepEqual(matchingLight.map, [255,248,233,255]); assert.deepEqual(matchingLight.topbarBorder, [159,130,96,255]);
    const dark = await toggleLocal('dark');
    assert.deepEqual(dark.primary, [104,67,134,255], 'native purple button replaces neither theme nor palette');
    await shot(page, 'tapl-local-dark-vscode-light');
    await page.evaluate(() => window.__applyHostTheme('vscode-dark'));
    const matchingDark = await appearance('dark'); assert.deepEqual(matchingDark.map, original.map); assert.deepEqual(matchingDark.topbarBorder, [77,123,158,255]);
    await page.evaluate(() => document.body.style.setProperty('--vscode-editor-border', 'rgba(22,188,144,.4)'));
    assert.equal(await page.locator('.wb-topbar').evaluate(element => getComputedStyle(element).borderBottomColor), 'rgba(22, 188, 144, 0.4)', 'matching native border alpha stays exact');
    await toggleLocal('light'); await toggleLocal('dark'); assert.equal(await page.locator('.wb-topbar').evaluate(element => getComputedStyle(element).borderBottomColor), 'rgba(22, 188, 144, 0.4)');
    await page.evaluate(() => window.__applyHostTheme('vscode-high-contrast'));
    assert.deepEqual((await colors()).topbarBorder, [255,224,102,255]);
    const hcLight = await toggleLocal('light'); assert.ok(contrast(hcLight.topbarBorder, hcLight['page-bg']) >= 3, 'opposite high-contrast border remains visible');
    await page.evaluate(() => window.__applyHostTheme('vscode-high-contrast-light'));
    assert.deepEqual((await colors()).topbarBorder, [103,79,190,255]);
    const hcDark = await toggleLocal('dark'); assert.ok(contrast(hcDark.topbarBorder, hcDark['page-bg']) >= 3);
    await page.evaluate(() => {
      document.body.style.removeProperty('--vscode-input-foreground');
      window.postMessage({...window.__lastNativeView, workspace: '/native/second-workspace'}, '*');
    });
    await appearance('dark'); await shot(page, 'tapl-local-dark-high-contrast-light');
    for (const [mode, tone, ink] of [['vscode-light', 'dark', '#000000'], ['vscode-dark', 'light', '#ffffff']]) {
      await page.evaluate(({mode, ink}) => {
        window.__applyHostTheme(mode);
        for (const name of ['descriptionForeground','focusBorder','textLink-foreground','testing-iconPassed','editorWarning-foreground','errorForeground','editorInfo-foreground','testing-iconSkipped','charts-purple','charts-orange'])
          document.body.style.setProperty(`--vscode-${name}`, ink);
      }, {mode, ink});
      if (await page.locator('html').getAttribute('data-tapl-native-tone') !== tone) await toggleLocal(tone);
      await appearance(tone);
    }
    assert.deepEqual(errors, []);
  } finally {await page.close();}
});

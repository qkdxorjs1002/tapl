const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { spawn, spawnSync } = require('node:child_process');
const { cpSync, mkdtempSync, mkdirSync, symlinkSync, rmSync, writeFileSync } = require('node:fs');
const path = require('node:path');
const { tmpdir } = require('node:os');
const { chromium, expect } = require('@playwright/test');

const extension = path.resolve(__dirname, '../..');
const python = process.env.TAPL_PYTHON || path.resolve(extension, '../tapl/.venv/bin/python');
const temp = mkdtempSync(path.join(tmpdir(), 'tapl-product-tour-'));
const version = '2.23.0';
const historyKey = 'tapl.viewer.product-tour.v1';
const servers = [];
let browser, origin, unconnectedOrigin, currentReleaseOrigin;

function buildFixtureAssets(buildVersion = version) {
  const staging = path.join(temp, `extension-${buildVersion}`);
  mkdirSync(staging);
  cpSync(path.join(extension, 'src'), path.join(staging, 'src'), { recursive: true });
  cpSync(path.join(extension, 'vite.config.ts'), path.join(staging, 'vite.config.ts'));
  symlinkSync(path.join(extension, 'node_modules'), path.join(staging, 'node_modules'), 'dir');
  writeFileSync(path.join(staging, 'package.json'), JSON.stringify({ ...require('../../package.json'), version: buildVersion }));
  const build = spawnSync(process.execPath, [path.join(extension, 'node_modules/vite/bin/vite.js'), 'build'], { cwd: staging, encoding: 'utf8' });
  assert.equal(build.status, 0, build.stdout + build.stderr);
  return path.join(staging, 'webview-dist');
}

async function serve(assets, extra = []) {
  const workspace = path.join(temp, 'workspace');
  const fixture = path.join(extension, 'tests/fixtures/workbench.py');
  const server = spawn(python, [fixture, '--workspace', workspace, '--port', '0', '--asset-root', assets, ...extra]);
  servers.push(server);
  return new Promise((resolve, reject) => {
    let stderr = '';
    const timer = setTimeout(() => reject(new Error('Viewer startup timed out: ' + stderr)), 15000);
    server.stderr.on('data', chunk => { stderr += chunk; });
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.once('exit', () => { clearTimeout(timer); reject(new Error(stderr)); });
    server.stdout.on('data', chunk => {
      const address = String(chunk).match(/tapl viewer: (http:\/\/\S+)/);
      if (address) { clearTimeout(timer); resolve(address[1]); }
    });
  });
}

before(async () => {
  const assets = buildFixtureAssets();
  origin = await serve(assets);
  unconnectedOrigin = await serve(assets, ['--without-default']);
  currentReleaseOrigin = await serve(buildFixtureAssets('2.24.0'));
  browser = process.env.WEBAPP_TESTING_CDP_URL
    ? await chromium.connectOverCDP(process.env.WEBAPP_TESTING_CDP_URL)
    : await chromium.launch({
      ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : { channel: 'chrome' }),
      headless: process.env.TAPL_TOUR_HEADED !== '1'
    });
});
after(async () => {
  await browser?.close();
  for (const server of servers) {
    if (server.exitCode != null) continue;
    const done = new Promise(resolve => server.once('exit', resolve));
    server.kill();
    await done;
  }
  rmSync(temp, { recursive: true, force: true });
});

async function open(options = {}) {
  const { history, failStorage, emptyRun, url = origin, ...view } = options;
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, locale: 'en-US', ...view });
  const errors = [];
  const commands = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (/violates.*Content Security Policy/.test(message.text())) errors.push(message.text()); });
  page.on('request', request => {
    if (request.url().endsWith('/api/message')) commands.push(request.postDataJSON()?.command);
  });
  await page.route('https://api.github.com/repos/qkdxorjs1002/tapl/releases/latest', route =>
    route.fulfill({ json: { tag_name: 'v9.0.0', draft: false, prerelease: false } }));
  if (emptyRun) await page.route('**/api/message', async route => {
    const response = await route.fetch();
    const payload = await response.json();
    if (payload.view?.type === 'overview') {
      Object.assign(payload.view.status, { active_run: null, active_runs: [], plans: [], tasks: [] });
    }
    if (payload.capabilities) payload.capabilities.associativeMemory = false;
    await route.fulfill({ response, json: payload });
  });
  if (history || failStorage) await page.addInitScript(({ key, history, failStorage }) => {
    if (history) localStorage.setItem(key, JSON.stringify(history));
    if (failStorage) {
      const write = Storage.prototype.setItem;
      Storage.prototype.setItem = function (target, value) {
        if (target === key) throw new Error('Test: tour storage is blocked');
        return write.call(this, target, value);
      };
    }
  }, { key: historyKey, history, failStorage });
  await page.goto(url);
  if (url === origin && !emptyRun) await expect(page.locator('.wb-run-mindmap')).toBeVisible();
  return { page, errors, commands };
}
const help = page => page.locator('[data-tour-focus-return]');
const card = page => page.locator('.tapl-tour-card');
const panel = page => page.locator('.tapl-tour-help');
const dialog = page => page.locator('.tapl-tour-popover');
const readHistory = page => page.evaluate(key => JSON.parse(localStorage.getItem(key) ?? 'null'), historyKey);

async function screenshot(page, name) {
  const directory = process.env.TAPL_SCREENSHOT_DIR;
  if (!directory) return;
  mkdirSync(directory, { recursive: true });
  await page.screenshot({ path: path.join(directory, name + '.png'), animations: 'disabled' });
}

async function assertEntryFits(entry) {
  assert.equal(await entry.evaluate(element => Array.from(element.querySelectorAll('button')).every(button =>
    button.scrollWidth <= button.clientWidth + 1 && button.scrollHeight <= button.clientHeight + 1
  )), true);
}

async function step(page, id, next, focusTarget) {
  const popup = dialog(page);
  await expect(popup).toHaveAttribute('data-tour-step', id);
  await expect(popup).toHaveAttribute('aria-modal', 'true');
  await expect(popup).not.toHaveAttribute('aria-busy', 'true');
  const box = await popup.boundingBox();
  const viewport = page.viewportSize();
  assert.ok(box.x >= 0 && box.y >= 0 && box.x + box.width <= viewport.width && box.y + box.height <= viewport.height, JSON.stringify(box));
  if (focusTarget) await expect(page.locator(`[data-tapl-tour="${focusTarget}"].driver-active-element`).first()).toBeVisible();
  await expect(popup.getByRole('button', { name: next, exact: true })).toBeInViewport();
  return popup.getByRole('button', { name: next, exact: true });
}

test('first visit in English completes five steps, preserves the page and reopens from Help', async () => {
  const { page, errors, commands } = await open({ colorScheme: 'light' });
  try {
    const originalUrl = page.url();
    await expect(card(page)).toContainText('New to TAPL?');
    assert.deepEqual(await readHistory(page), { releaseSeenThrough: version });
    await assertEntryFits(card(page));
    await screenshot(page, 'web-welcome-light');
    await card(page).getByRole('button', { name: 'Quick start' }).click();
    const next = await step(page, 'run-tabs', 'Next', 'run-tabs');
    await expect(dialog(page)).toContainText('Example scenario');
    await expect(page.locator('[data-tapl-tour="run-tabs"]')).toContainText('Export search results');
    await expect(dialog(page).getByRole('button', { name: 'Previous' })).toBeDisabled();
    await screenshot(page, 'web-desktop-light');
    for (let index = 0; index < 4; index++) {
      await page.keyboard.press('Tab');
      assert.equal(await dialog(page).evaluate(element => element.contains(document.activeElement)), true);
    }
    await next.focus();
    await page.keyboard.press('Enter');
    await step(page, 'run-map', 'Next', 'run-map');
    await dialog(page).getByRole('button', { name: 'Previous' }).click();
    await (await step(page, 'run-tabs', 'Next')).click();
    await (await step(page, 'run-map', 'Next')).click();
    await (await step(page, 'follow', 'Next', 'follow')).click();
    await (await step(page, 'record-search', 'Next', 'record-search')).click();
    await (await step(page, 'memory-list', 'Done', 'memory-list')).click();
    await expect(dialog(page)).toHaveCount(0);
    await expect(help(page)).toBeFocused();
    await expect(page.locator('[data-tour-preview-content]')).toHaveCount(0);
    await expect(page.locator('.wb-run-mindmap')).toBeVisible();
    assert.equal(page.url(), originalUrl);
    assert.ok(!commands.some(command => ['records', 'memories', 'openRun', 'getSettings'].includes(command)));
    await expect(card(page)).toContainText('Keep exploring');
    await card(page).getByRole('button', { name: 'Current RUN' }).click();
    await expect(page.locator('.wb-run-mindmap')).toBeVisible();
    assert.deepEqual(await readHistory(page), { intro: 'completed', releaseSeenThrough: version });
    await page.reload();
    await expect(page.locator('.wb-run-mindmap')).toBeVisible();
    await expect(card(page)).toHaveCount(0);
    await help(page).click();
    await assertEntryFits(panel(page));
    await screenshot(page, 'web-help-light');
    await panel(page).getByRole('button', { name: 'Find blocked tasks' }).click();
    await (await step(page, 'task-filter', 'Next', 'task-filter')).click();
    await step(page, 'blocked-task', 'Done', 'blocked-task');
    await expect(page.locator('[data-tour-preview-content]')).toContainText('The sample report is waiting for approval.');
    await page.keyboard.press('Escape');
    await expect(dialog(page)).toHaveCount(0);
    await expect(help(page)).toBeFocused();
    await help(page).click();
    await panel(page).getByRole('button', { name: 'Change display settings' }).click();
    await (await step(page, 'display-settings', 'Next', 'display-settings')).click();
    await (await step(page, 'viewer-brightness', 'Done', 'theme')).click();
    assert.ok(!commands.includes('getSettings'));
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('Korean dark modals fit a narrow reduced-motion viewport and Later lasts for the page', async () => {
  const { page, errors } = await open({
    viewport: { width: 320, height: 510 }, locale: 'ko-KR', colorScheme: 'dark', reducedMotion: 'reduce', isMobile: true, hasTouch: true
  });
  try {
    await assertEntryFits(card(page));
    await expect(card(page)).toContainText('Agent가 어디까지 진행했고');
    await card(page).getByRole('button', { name: '나중에' }).click();
    await expect(card(page)).toHaveCount(0);
    await help(page).click();
    await panel(page).getByRole('button', { name: '빠른 시작' }).click();
    for (const id of ['run-tabs', 'run-map', 'follow', 'record-search']) {
      const next = await step(page, id, '다음', id);
      if (id === 'run-tabs') {
        await expect(dialog(page)).toContainText('예시 화면');
        await expect(dialog(page).locator('.driver-popover-title')).toHaveText('RUN 선택하기');
        await expect(dialog(page)).toContainText('RUN은 Agent 작업 한 건의 기록입니다.');
      }
      if (id === 'run-map') await expect(dialog(page).locator('.driver-popover-title')).toHaveText('PLAN과 TASK 읽기');
      if (id === 'follow') await screenshot(page, 'web-mobile-dark');
      await next.click();
    }
    await step(page, 'memory-list', '마치기', 'memory-list');
    await dialog(page).getByRole('button', { name: '닫기' }).click();
    await expect(help(page)).toBeFocused();
    assert.equal((await readHistory(page)).intro, undefined);
    await page.reload();
    await expect(page.locator('.wb-run-mindmap')).toBeVisible();
    await card(page).getByRole('button', { name: '다시 보지 않기' }).click();
    await page.reload();
    await expect(page.locator('.wb-run-mindmap, .wb-memory-page')).toBeVisible();
    await expect(card(page)).toHaveCount(0);
    assert.deepEqual(await readHistory(page), { intro: 'dismissed', releaseSeenThrough: version });
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('upgrade tour tracks the installed build, omits VS Code-only features in the browser, and retains a downgrade baseline', async () => {
  const updated = await open({ history: { intro: 'completed', releaseSeenThrough: '2.22.1' }, colorScheme: 'dark' });
  try {
    await expect(card(updated.page)).toContainText('v2.23.0');
    await expect(updated.page.locator('.tapl-viewer-version-latest')).toHaveText('v9.0.0');
    await card(updated.page).getByRole('button', { name: 'See what’s new' }).click();
    const next = await step(updated.page, 'close-read-only-run', 'Next', 'record-search');
    await screenshot(updated.page, 'web-upgrade-dark');
    await next.click();
    await (await step(updated.page, 'memory-source-hints', 'Done')).click();
    await expect(dialog(updated.page)).toHaveCount(0);
    await expect(card(updated.page)).toHaveCount(0);
    assert.deepEqual(await readHistory(updated.page), { intro: 'completed', releaseSeenThrough: version });
    assert.deepEqual(updated.errors, []);
  } finally { await updated.page.close(); }
  const downgraded = await open({ history: { intro: 'completed', releaseSeenThrough: '2.24.0-rc.1' } });
  try {
    await expect(card(downgraded.page)).toHaveCount(0);
    assert.equal((await readHistory(downgraded.page)).releaseSeenThrough, '2.24.0-rc.1');
    await help(downgraded.page).click();
    await expect(panel(downgraded.page).getByRole('button', { name: /What’s new/ })).toContainText('v2.23.0');
  } finally { await downgraded.page.close(); }
});

test('workspace setup takes precedence, and unavailable persistence still permits manual guides', async () => {
  const setup = await open({ url: unconnectedOrigin });
  try {
    await expect(setup.page.locator('.wb-workspace-dialog')).toContainText('Open a project folder with TAPL records');
    await expect(card(setup.page)).toHaveCount(0);
    await screenshot(setup.page, 'web-workspace-setup');
  } finally { await setup.page.close(); }
  const blocked = await open({ failStorage: true });
  try {
    await card(blocked.page).getByRole('button', { name: 'Don’t show again' }).click();
    await expect(card(blocked.page)).toHaveCount(0);
    assert.equal(await readHistory(blocked.page), null);
    await help(blocked.page).click();
    await panel(blocked.page).getByRole('button', { name: 'Quick start' }).click();
    await step(blocked.page, 'run-tabs', 'Next');
    await blocked.page.keyboard.press('Escape');
    assert.deepEqual(blocked.errors, []);
  } finally { await blocked.page.close(); }
});

test('2.24.0 introduces the archive tab, delegated model and Viewer link in order', async () => {
  const { page, errors } = await open({
    url: currentReleaseOrigin, history: { intro: 'completed', releaseSeenThrough: version }, locale: 'ko-KR'
  });
  try {
    const offer = card(page);
    await expect(offer).toContainText('v2.24.0');
    await offer.getByRole('button', { name: '새 기능 보기' }).click();
    const next = await step(page, 'keep-archived-run', '다음', 'run-tabs');
    await expect(page.locator('[data-tapl-tour="run-tabs"]')).toHaveClass(/wb-run-tab-temporary/);
    await next.click();
    await (await step(page, 'delegated-task-model', '다음', 'delegated-task-model')).click();
    await (await step(page, 'open-viewer-link', '마치기')).click();
    await expect(dialog(page)).toHaveCount(0);
    assert.deepEqual(await readHistory(page), { intro: 'completed', releaseSeenThrough: '2.24.0' });
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('an empty workspace highlights sample runs, tasks, records, memories and references', async () => {
  const { page, errors, commands } = await open({ emptyRun: true, viewport: { width: 380, height: 540 } });
  try {
    await card(page).getByRole('button', { name: 'Quick start' }).click();
    await (await step(page, 'run-tabs', 'Next', 'run-tabs')).click();
    await (await step(page, 'run-map', 'Next', 'run-map')).click();
    await (await step(page, 'follow', 'Next', 'follow')).click();
    await (await step(page, 'record-search', 'Next', 'record-search')).click();
    await (await step(page, 'memory-list', 'Done', 'memory-list')).click();
    await expect(card(page)).toContainText('Keep exploring');
    await expect(page.locator('.wb-run-tabs [role="tab"]')).toHaveCount(0);
    await expect(page.locator('[data-tour-preview-content]')).toHaveCount(0);
    await help(page).click();
    await panel(page).getByRole('button', { name: 'Read sources and usage' }).click();
    await (await step(page, 'run-references', 'Next', 'run-references')).click();
    await step(page, 'reference-usage', 'Done', 'reference-stage');
    await expect(page.locator('[data-tapl-tour="reference-stage"].driver-active-element')).toHaveAttribute('data-stage', 'used');
    await page.keyboard.press('Escape');
    assert.ok(!commands.some(command => ['records', 'memories', 'openRun', 'openMemory', 'getSettings'].includes(command)));
    await help(page).click();
    await panel(page).getByRole('button', { name: 'Quick start' }).click();
    await (await step(page, 'run-tabs', 'Next')).click();
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-tour-preview-content]')).toHaveCount(0);
    await page.getByRole('button', { name: 'Navigation' }).click();
    await page.locator('[data-wb-focus="nav:records"]').click();
    await expect(page.locator('[data-tapl-tour="record-search"]')).toBeVisible();
    assert.deepEqual(errors, []);
  } finally {
    await page.unrouteAll({ behavior: 'wait' });
    await page.close();
  }
});

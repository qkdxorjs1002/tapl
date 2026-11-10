const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { spawn, spawnSync } = require('node:child_process');
const { mkdtempSync, mkdirSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { chromium } = require('@playwright/test');

let server, browser, origin, python;
const fixture = path.resolve(__dirname, '../fixtures/workbench.py');
const workspace = mkdtempSync(path.join(tmpdir(), 'tapl-workbench-'));
const secondWorkspace = path.join(workspace, 'second');
async function startServer(extra = []) {
  const process = spawn(python, [fixture, '--workspace', workspace, '--port', '0', ...extra], { stdio: ['ignore', 'pipe', 'pipe'] });
  const url = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Viewer startup timed out')), 15000);
    process.once('error', error => { clearTimeout(timer); reject(error); });
    process.once('exit', code => { clearTimeout(timer); reject(new Error(`Viewer exited: ${code}`)); });
    process.stdout.on('data', chunk => { const match = String(chunk).match(/tapl viewer: (http:\/\/\S+)/); if (match) { clearTimeout(timer); resolve(match[1]); } });
    process.stderr.on('data', chunk => global.process.stderr.write(chunk));
  });
  return { process, url };
}
before(async () => {
  python = process.env.TAPL_PYTHON || path.resolve(__dirname, '../../../tapl/.venv/bin/python');
  const started = await startServer(); server = started.process; origin = started.url;
  const seeded = spawnSync(python, [fixture, '--workspace', secondWorkspace, '--seed-only'], { encoding: 'utf8' });
  assert.equal(seeded.status, 0, seeded.stderr);
  browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : { channel: 'chrome' });
});
after(async () => { await browser?.close(); if (server) { const done = new Promise(resolve => server.once('exit', resolve)); server.kill(); await done; } rmSync(workspace, { recursive: true, force: true }); });
async function shot(page, name) {
  const directory = process.env.TAPL_SCREENSHOT_DIR;
  if (directory) { mkdirSync(directory, { recursive: true }); await page.screenshot({ path: path.join(directory, `${name}.png`), animations: 'disabled' }); }
}

async function openPage() {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'ko-KR' });
  page.setDefaultTimeout(6000);
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(origin);
  await page.locator('.wb-current-overview').waitFor();
  return { page, errors };
}

test('real Viewer keeps RUN context, record navigation, preferences and fixed shell', { timeout: 90000 }, async () => {
  const { page, errors } = await openPage();
  try {
    assert.equal(await page.getByRole('tab').count(), 2);
    assert.equal(await page.locator('.wb-run-facts > div').count(), 3, 'missing difficulty is omitted');
    assert.equal(await page.locator('[data-wb-focus="nav:current"] .wb-nav-counter').textContent(), '25%');
    const lane = page.locator('[data-wb-track="flow"]');
    await lane.evaluate(el => el.scrollLeft = 500);
    assert.ok(await lane.evaluate(el => el.scrollLeft) > 0);
    const before = await page.locator('.wb-topbar').boundingBox();
    await page.locator('.wb-page-scroll').evaluate(el => el.scrollTop = 400);
    assert.deepEqual(await page.locator('.wb-topbar').boundingBox(), before);
    assert.equal(await page.evaluate(() => scrollY), 0);

    await page.locator('[data-wb-focus="nav:tasks"]').click();
    await page.locator('[data-wb-focus="filter:In Progress"]').click();
    await page.locator('[data-wb-focus="task-query"]').fill('task 1');
    const task = page.locator('.wb-task-title').first();
    const title = await task.innerText();
    await task.click();
    await page.locator('.wb-record-page').waitFor();
    assert.ok((await page.locator('.wb-record-page').innerText()).includes(title.split('\n').pop()));
    const heading = await page.locator('.wb-record-page h1').innerText();
    await page.locator('.wb-run-tab[aria-selected="true"]').click();
    assert.equal(await page.locator('.wb-record-page h1').innerText(), heading);
    assert.equal(await page.locator('.wb-back').count(), 1, 'same selected RUN preserves return trail');
    assert.equal(await page.locator('.wb-record-page .tapl-card').count(), 0);
    await shot(page, 'task-detail-ko-light');

    await page.locator('.wb-back').click();
    await page.locator('.wb-tasks-table').waitFor();
    assert.equal(await page.locator('[data-wb-focus="task-query"]').inputValue(), 'task 1');
    assert.equal(await page.locator('[data-wb-focus="filter:In Progress"]').getAttribute('aria-pressed'), 'true');

    await page.locator('[data-wb-focus="nav:records"]').click();
    await page.locator('.wb-search-group').first().waitFor();
    assert.equal(await page.locator('[data-wb-focus="record-scope"]').inputValue(), 'all');
    assert.equal(await page.locator('.wb-search-group-header[aria-expanded="true"]').count(), 0);
    const archive = page.locator('.wb-search-group').filter({ hasText: 'Archived design' });
    await archive.locator('.wb-search-group-header').click();
    await archive.locator('.wb-source-run-link').click();
    await page.locator('.wb-run-tab-temporary').waitFor();
    assert.equal(await page.getByRole('tab').count(), 3);
    await page.locator('.wb-back').click();
    await page.locator('.wb-search-group').first().waitFor();
    assert.equal(await page.locator('.wb-search-group-header[aria-expanded="true"]').count(), 1);
    await archive.locator('.wb-source-run-link').click();
    await page.locator('.wb-run-tab-temporary').waitFor();
    await page.getByRole('tab', { name: /Second active RUN/ }).click();
    await page.locator('.wb-current-overview').waitFor();
    assert.equal(await page.locator('.wb-run-tab-temporary').count(), 0);
    assert.equal(await page.getByRole('tab').count(), 2);
    assert.ok((await page.locator('.wb-current-overview').innerText()).includes('Second RUN task'));

    await page.locator('.wb-language-menu summary').click();
    await page.getByRole('button', { name: 'English', exact: true }).click();
    await page.getByRole('button', { name: 'Use dark theme', exact: true }).click();
    await page.reload();
    await page.locator('.wb-current-overview').waitFor();
    assert.equal(await page.locator('html').getAttribute('lang'), 'en');
    assert.equal(await page.locator('html').getAttribute('data-tapl-theme'), 'dark');
    assert.equal(await page.locator('.wb-back').count(), 0, 'reload clears historical Back');
    const picker = page.locator('.wb-workspace-heading button');
    assert.equal(await picker.count(), 1);
    assert.equal(await page.locator('.wb-workspace-switch').count(), 0, 'browser uses the heading icon');
    await picker.click();
    await page.locator('#tapl-workspace-path').waitFor();
    await page.locator('dialog.wb-workspace-dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.locator('.wb-current-overview').waitFor();
    assert.ok((await page.locator('.wb-current-overview').innerText()).includes('Second RUN task'));

    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('Explore stays reachable on short screens and closes across responsive navigation', { timeout: 60000 }, async () => {
  const { page, errors } = await openPage();
  try {
    const trigger = page.locator('[data-wb-focus="explore:TASK"]');
    await trigger.hover();
    await page.locator('.wb-explore-panel').waitFor();
    await page.locator('.wb-fold-list button').first().hover();
    assert.equal(await trigger.getAttribute('aria-expanded'), 'true');
    await page.locator('.wb-fold-list button').first().click();
    await page.locator('.wb-record-page').waitFor();
    assert.equal(await page.locator('.wb-explore-panel').count(), 0);
    await page.setViewportSize({ width: 1280, height: 420 });
    const sidebar = page.locator('.wb-sidebar');
    assert.ok(await sidebar.evaluate(el => el.scrollHeight > el.clientHeight));
    await page.locator('.wb-discard-button').scrollIntoViewIfNeeded();
    assert.ok(await page.locator('.wb-discard-button').isVisible());
    await trigger.click();
    await page.locator('.wb-explore-panel').waitFor();
    await page.setViewportSize({ width: 600, height: 750 });
    await page.waitForFunction(() => document.querySelector('.wb-sidebar').inert);
    assert.equal(await page.locator('.wb-explore-panel').count(), 0);
    await page.locator('.wb-mobile-menu').click();
    await page.locator('[data-wb-focus="explore:PLAN"]').click();
    await page.locator('.wb-explore-panel').waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.wb-explore-panel').count(), 0);
    assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});


test('theme control reflects automatic dark mode and follows system changes until overridden', async () => {
  const page = await browser.newPage({ locale: 'en-US', colorScheme: 'dark', viewport: { width: 1280, height: 900 } });
  page.setDefaultTimeout(6000);
  try {
    await page.goto(origin);
    await page.locator('.wb-current-overview').waitFor();
    await page.getByRole('button', { name: 'Use light theme', exact: true }).waitFor();
    await page.emulateMedia({ colorScheme: 'light' });
    await page.getByRole('button', { name: 'Use dark theme', exact: true }).click();
    await page.emulateMedia({ colorScheme: 'light' });
    assert.equal(await page.locator('html').getAttribute('data-tapl-theme'), 'dark');
  } finally { await page.close(); }
});

test('workspace modal preserves RUN, filters, scroll and focus on cancel, invalid and same-folder selections', { timeout: 45000 }, async () => {
  const { page, errors } = await openPage();
  try {
    const current = await page.locator('.wb-run-tab[aria-selected="true"]').getAttribute('title');
    await page.locator('.wb-page-scroll').evaluate(el => el.scrollTop = 180);
    const scroll = await page.locator('.wb-page-scroll').evaluate(el => el.scrollTop);
    const picker = page.locator('[data-wb-focus="workspace-picker"]');
    await picker.click();
    const modal = page.locator('dialog.wb-workspace-dialog');
    await modal.waitFor();
    assert.equal(await page.locator('.wb-page-scroll').evaluate(el => el.scrollTop), scroll);
    await shot(page, 'workspace-modal-ko-light');
    await page.keyboard.press('Escape');
    assert.equal(await modal.count(), 0);
    assert.equal(await picker.evaluate(el => el === document.activeElement), true);
    assert.equal(await page.locator('.wb-run-tab[aria-selected="true"]').getAttribute('title'), current);
    await page.locator('[data-wb-focus="nav:tasks"]').click();
    await page.locator('[data-wb-focus="filter:In Progress"]').click();
    await page.locator('[data-wb-focus="task-query"]').fill('task 1');
    await picker.click();
    await modal.locator('input').fill(path.join(workspace, 'missing'));
    await modal.locator('button[type=submit]').click();
    await modal.getByRole('alert').waitFor();
    assert.equal(await page.locator('[data-wb-focus="task-query"]').inputValue(), 'task 1');
    assert.equal(await page.locator('.wb-tasks-table').count(), 1);
    await modal.getByRole('button', { name: '취소', exact: true }).click();
    assert.equal(await page.locator('[data-wb-focus="filter:In Progress"]').getAttribute('aria-pressed'), 'true');
    await picker.click();
    await modal.locator('input').fill(workspace);
    await modal.locator('button[type=submit]').click();
    await modal.waitFor({ state: 'detached' });
    assert.equal(await page.locator('[data-wb-focus="task-query"]').inputValue(), 'task 1');
    assert.equal(await page.locator('.wb-run-tab[aria-selected="true"]').getAttribute('title'), current);
    await picker.click();
    await modal.locator('input').fill(secondWorkspace);
    await modal.locator('button[type=submit]').click();
    await modal.waitFor({ state: 'detached' });
    await page.locator('.wb-current-overview').waitFor();
    assert.ok((await picker.getAttribute('title')).includes(secondWorkspace));
    assert.notEqual(await page.locator('.wb-run-tab[aria-selected="true"]').getAttribute('title'), current);
    await page.locator('[data-wb-focus="nav:tasks"]').click();
    assert.equal(await page.locator('[data-wb-focus="task-query"]').inputValue(), '');
    assert.equal(await page.locator('[data-wb-focus="filter:all"]').getAttribute('aria-pressed'), 'true');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('PLAN, FINDING, memories and diagnostics use reading pages and nested vertical fields', { timeout: 45000 }, async () => {
  const { page, errors } = await openPage();
  try {
    await page.locator('.wb-plan-summary').first().click();
    await page.locator('.wb-record-page').waitFor();
    assert.equal(await page.locator('.wb-reading-section h2').filter({ hasText: '목적' }).count(), 1);
    assert.equal(await page.locator('.wb-reading-section h2').filter({ hasText: '요구사항' }).count(), 1);
    await shot(page, 'plan-detail-ko-light');
    await page.locator('.wb-back').click();
    await page.locator('[data-wb-focus="explore:FINDING"]').click();
    await page.locator('.wb-fold-list button').first().click();
    await page.locator('.wb-record-page').waitFor();
    assert.equal(await page.evaluate(() => window.untrusted), undefined);
    assert.ok((await page.locator('.wb-record-page').innerText()).includes('<script>window.untrusted = true</script>'));
    await shot(page, 'finding-detail-ko-light');
    await page.locator('[data-wb-focus="nav:memories"]').click();
    await page.locator('.wb-memory-card').first().waitFor();
    assert.equal(await page.locator('.wb-memory-card').count(), 2);
    assert.equal(await page.locator('.tapl-memory-list,.tapl-card').count(), 0);
    await shot(page, 'memories-ko-light');
    await page.locator('.wb-memory-card').filter({ hasText: 'original contrast finding' }).locator('.wb-memory-open').click();
    await page.locator('.wb-memory-source-preview').waitFor();
    await shot(page, 'memory-detail-ko-light');
    await page.locator('.wb-memory-origin button').click();
    await page.locator('.wb-record-page').waitFor();
    assert.equal(await page.locator('.wb-record-page h1').innerText(), 'Archived contrast finding');
    assert.equal(await page.locator('.wb-run-tab-temporary').count(), 1);
    await page.locator('.wb-back').click();
    await page.locator('.wb-memory-source-preview').waitFor();
    await page.getByRole('button', { name: '디버그', exact: true }).click();
    await page.locator('.wb-secondary-event').nth(2).waitFor();
    const rows = await page.locator('.wb-secondary-event').evaluateAll(elements => elements.map(el => {
      const row = el.getBoundingClientRect(), line = getComputedStyle(el, '::before');
      return { top: row.top, bottom: row.bottom, lineTop: row.top + parseFloat(line.top), lineBottom: line.bottom === 'auto' ? row.top + parseFloat(line.top) + parseFloat(line.height) : row.bottom - parseFloat(line.bottom) };
    }));
    for (let i = 0; i < rows.length - 1; i++) assert.ok(Math.abs(rows[i].lineBottom - rows[i + 1].lineTop) < 1, 'continuous event connector');
    await shot(page, 'diagnostics-ko-light');
    await page.setViewportSize({ width: 650, height: 700 });
    assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('icon tooltips work on hover/focus and actual status colors stay distinct in both themes', { timeout: 30000 }, async () => {
  const { page, errors } = await openPage();
  try {
    const picker = page.locator('[data-wb-focus="workspace-picker"]');
    await picker.hover();
    await page.getByRole('tooltip').waitFor();
    assert.equal(await page.getByRole('tooltip').innerText(), await picker.getAttribute('aria-label'));
    const rect = await page.getByRole('tooltip').boundingBox();
    assert.ok(rect.x >= 0 && rect.x + rect.width <= 1440);
    await page.keyboard.press('Escape');
    await page.locator('.wb-language-menu summary').focus();
    await page.getByRole('tooltip').waitFor();
    assert.equal(await page.getByRole('tooltip').innerText(), '언어');
    await page.keyboard.press('Escape');
    const colors = () => page.locator('.wb-flow-heading .wb-status-label').evaluateAll(elements => elements.map(el => getComputedStyle(el).color));
    assert.equal(new Set(await colors()).size, 4);
    await page.locator('.wb-brand-actions > button').click();
    await page.waitForFunction(() => document.documentElement.dataset.taplTheme === 'dark');
    assert.equal(new Set(await colors()).size, 4);
    await shot(page, 'current-ko-dark');
    await page.locator('.wb-flow-task').first().click();
    await page.locator('.wb-record-page').waitFor();
    await page.locator('.wb-record-disclosures > details').filter({ hasText: 'nested' }).locator('summary').first().click();
    assert.ok(await page.locator('.wb-value-branch').count() > 0);
    assert.equal(await page.locator('.wb-value-tree pre').count(), 0);
    await shot(page, 'task-fields-ko-dark');
    await page.setViewportSize({ width: 650, height: 700 });
    const body = await page.locator('.wb-reading-body').boundingBox(), properties = await page.locator('.wb-record-properties').boundingBox();
    assert.ok(body.y < properties.y, 'reading body precedes properties on narrow screens');
    assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true);
    await shot(page, 'task-detail-narrow-dark');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('an unselected initial workspace opens the same modal over the fixed shell', { timeout: 30000 }, async () => {
  const extra = await startServer(['--without-default']);
  const page = await browser.newPage({ viewport: { width: 1000, height: 700 }, locale: 'en-US' });
  try {
    await page.goto(extra.url);
    await page.locator('dialog.wb-workspace-dialog').waitFor();
    assert.equal(await page.locator('.tapl-workbench').count(), 1);
    assert.equal(await page.locator('.tapl-workspace-orbit,.tapl-workspace-card').count(), 0);
    await page.locator('#tapl-workspace-path').fill(workspace);
    await page.locator('.wb-workspace-dialog button[type=submit]').click();
    await page.locator('dialog.wb-workspace-dialog').waitFor({ state: 'detached' });
    await page.locator('.wb-current-overview').waitFor();
    await shot(page, 'workspace-initial-en');
  } finally { await page.close(); extra.process.kill(); }
});

test('archive fallback, events, recoverable errors and unsupported memory share the new surfaces', { timeout: 30000 }, async () => {
  const { page, errors } = await openPage();
  let failDebug = false, unsupportedMemory = false;
  await page.route('**/api/message', async route => {
    const request = route.request().postDataJSON();
    if (request.command === 'debug' && failDebug) {
      failDebug = false;
      return route.fulfill({ json: { type: 'error', message: 'Temporary viewer connection failure', locale: 'ko', layout: 'auto' } });
    }
    if (request.command === 'openArchive' || (request.command === 'memories' && unsupportedMemory)) {
      const response = await route.fetch();
      const payload = await response.json();
      if (request.command === 'openArchive') delete payload.view.context;
      if (request.command === 'memories') payload.capabilities.associativeMemory = false;
      return route.fulfill({ response, json: payload });
    }
    return route.continue();
  });
  try {
    await page.locator('[data-wb-focus="nav:records"]').click();
    const group = page.locator('.wb-search-group').filter({ hasText: 'Archived design' });
    await group.locator('.wb-search-group-header').click();
    await group.locator('.wb-search-result').first().click();
    await page.locator('.wb-record-page').waitFor();
    await page.locator('.wb-reading-archive').click();
    await page.locator('.wb-secondary-record').waitFor();
    assert.ok((await page.locator('.wb-secondary').innerText()).includes('Archived contrast finding'));
    await shot(page, 'archive-fallback-ko-light');
    await page.locator('.wb-secondary-footer > button').click();
    await page.locator('.wb-secondary-section').waitFor();
    await shot(page, 'archive-events-ko-light');
    failDebug = true;
    await page.getByRole('button', { name: '디버그', exact: true }).click();
    await page.getByRole('alert').waitFor();
    assert.ok((await page.getByRole('alert').innerText()).includes('Temporary viewer connection failure'));
    await shot(page, 'error-ko-light');
    await page.locator('.wb-secondary-actions > button').first().click();
    await page.locator('.wb-current-overview').waitFor();
    unsupportedMemory = true;
    await page.locator('[data-wb-focus="nav:memories"]').click();
    await page.locator('.wb-empty').waitFor();
    assert.equal(await page.locator('.wb-memory-card').count(), 0);
    await shot(page, 'memory-unsupported-ko-light');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('initial loading retains the fixed shell', { timeout: 30000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, locale: 'en-US' });
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/api/message', async route => { if (route.request().postDataJSON().command === 'ready') await gate; await route.continue(); });
  try {
    await page.goto(origin);
    await page.locator('.tapl-workbench').waitFor();
    await page.locator('.wb-secondary-loading').waitFor();
    assert.equal(await page.locator('.wb-sidebar').count(), 1);
    await shot(page, 'loading-en-light');
    release();
    await page.locator('.wb-current-overview').waitFor();
  } finally { release(); await page.close(); }
});

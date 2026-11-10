const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { chromium } = require('@playwright/test');

let server, browser, origin;
const workspace = mkdtempSync(path.join(tmpdir(), 'tapl-workbench-'));
before(async () => {
  const python = process.env.TAPL_PYTHON || path.resolve(__dirname, '../../../tapl/.venv/bin/python');
  server = spawn(python, [path.resolve(__dirname, '../fixtures/workbench.py'), '--workspace', workspace, '--port', '0'], { stdio: ['ignore', 'pipe', 'pipe'] });
  origin = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Viewer startup timed out')), 15000);
    server.once('error', reject);
    server.once('exit', code => reject(new Error(`Viewer exited: ${code}`)));
    server.stdout.on('data', chunk => { const match = String(chunk).match(/tapl viewer: (http:\/\/\S+)/); if (match) { clearTimeout(timer); resolve(match[1]); } });
    server.stderr.on('data', chunk => process.stderr.write(chunk));
  });
  browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : { channel: 'chrome' });
});
after(async () => { await browser?.close(); server?.kill(); rmSync(workspace, { recursive: true, force: true }); });

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
    await page.locator('.wb-legacy-view').waitFor();
    assert.ok((await page.locator('.wb-legacy-view').innerText()).includes(title.split('\n').pop()));
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
    await page.locator('.wb-back').click();
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
    await page.locator('.wb-legacy-view').waitFor();
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

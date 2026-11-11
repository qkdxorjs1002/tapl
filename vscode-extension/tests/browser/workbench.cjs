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
  await page.locator('.wb-run-mindmap').waitFor();
  return { page, errors };
}

test('icon navigation hides collapsed counts, expands over the map and preserves pinning and Explore focus', { timeout: 60000 }, async () => {
  const { page, errors } = await openPage();
  const shell = page.locator('.tapl-workbench'), sidebar = page.locator('.wb-sidebar');
  const pin = page.locator('[data-wb-focus="sidebar-pin"]');
  try {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    assert.equal(await shell.getAttribute('data-sidebar-expanded'), 'false');
    assert.equal((await sidebar.boundingBox()).width, 72);
    const navIcon = await page.locator('[data-wb-focus="nav:current"] > .wb-icon').boundingBox();
    assert.equal(await page.locator('.wb-management-actions > button').count(),1);
    assert.equal(await page.locator('.wb-management-actions > button').getAttribute('aria-label'),'디버그');
    for (const selector of ['[data-wb-focus="workspace-picker"] .wb-icon', '.wb-management-actions > button .wb-icon']) {
      const icon = await page.locator(selector).boundingBox();
      assert.ok(Math.abs(icon.x+icon.width/2-navIcon.x-navIcon.width/2)<1, selector);
      assert.equal(icon.width,17); assert.equal(icon.height,17);
    }
    const language = await page.locator('.wb-language-menu summary').boundingBox(), pinBox = await pin.boundingBox();
    const theme = await page.locator('[data-wb-focus="theme-toggle"]').boundingBox();
    assert.ok(language.x + language.width <= theme.x && theme.x + theme.width <= pinBox.x, 'pin is the rightmost control after language and theme');
    assert.equal(await page.locator('.wb-mm-top-controls button[aria-pressed]').count(),0,'map motion has no toggle');
    const tasks = page.locator('[data-wb-focus="nav:tasks"]');
    assert.equal(await page.locator('.wb-count-compact').count(),0);
    assert.equal(await tasks.locator('.wb-rail-count').isVisible(),false);
    assert.equal(await tasks.locator('.wb-count-full').textContent(), '24개');
    assert.ok((await tasks.getAttribute('aria-label')).includes('24개'));
    const canvas = await page.locator('.wb-run-mindmap').boundingBox();
    await tasks.hover();
    await page.waitForFunction(() => document.querySelector('.tapl-workbench').dataset.sidebarExpanded === 'true');
    assert.equal((await sidebar.boundingBox()).width, 256);
    assert.equal(await tasks.locator('.wb-rail-count').isVisible(),true);
    assert.equal(await tasks.locator('.wb-count-full').innerText(),'24개');
    assert.deepEqual(await page.locator('.wb-run-mindmap').boundingBox(), canvas, 'hover overlays rather than moves the canvas');
    await page.getByRole('tooltip').waitFor();
    assert.ok((await page.getByRole('tooltip').innerText()).includes('24개'));
    await sidebar.click({position:{x:16,y:4}});
    assert.equal(await shell.getAttribute('data-sidebar-expanded'),'true','inside clicks retain the expanded rail');
    await page.mouse.move(1000, 800);
    await page.waitForTimeout(250);
    assert.equal(await shell.getAttribute('data-sidebar-expanded'),'true','brief pointer departure keeps the panel open');
    await tasks.hover();
    await page.waitForTimeout(400);
    assert.equal(await shell.getAttribute('data-sidebar-expanded'),'true','re-entry cancels the pending collapse');
    await page.mouse.move(1000,800);
    assert.equal(await shell.getAttribute('data-sidebar-expanded'),'true');
    await page.mouse.down();
    await page.waitForFunction(() => document.querySelector('.tapl-workbench').dataset.sidebarExpanded === 'false',undefined,{timeout:250});
    await page.mouse.up();
    await pin.click();
    assert.equal(await shell.getAttribute('data-sidebar-pinned'), 'true');
    assert.equal((await page.locator('.wb-run-mindmap').boundingBox()).x, 256);
    await page.mouse.click(1000,800);
    assert.equal(await shell.getAttribute('data-sidebar-expanded'),'true','outside clicks preserve pinned navigation');
    await page.locator('[data-wb-focus="theme-toggle"]').click();
    await page.reload();
    await page.locator('.wb-run-mindmap').waitFor();
    assert.equal(await shell.getAttribute('data-sidebar-pinned'), 'true', 'theme persistence retains pin state');
    await pin.click();
    await page.mouse.move(1000, 800);
    await page.waitForFunction(() => document.querySelector('.tapl-workbench').dataset.sidebarExpanded === 'false');
    await page.locator('[data-wb-focus="explore:TASK"]').hover();
    await page.locator('.wb-fold-list button').first().hover();
    assert.equal(await shell.getAttribute('data-sidebar-expanded'), 'true', 'portal hover keeps navigation expanded');
    const box = await sidebar.boundingBox(), flyout = await page.locator('.wb-explore-panel').boundingBox();
    assert.ok(flyout.x >= box.x + box.width);
    await page.locator('.wb-explore-panel header h2').click();
    assert.equal(await shell.getAttribute('data-sidebar-expanded'),'true','portal clicks are inside navigation');
    await page.mouse.click(1000,800);
    await page.waitForFunction(() => document.querySelector('.tapl-workbench').dataset.sidebarExpanded === 'false',undefined,{timeout:250});
    assert.equal(await page.locator('.wb-explore-panel').count(),0);
    await page.locator('[data-wb-focus="explore:TASK"]').hover();
    await page.locator('.wb-fold-list button').first().waitFor();
    await page.locator('.wb-fold-list button').first().focus();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.wb-explore-panel').count(), 0);
    await page.keyboard.press('Tab');
    await page.locator('[data-wb-focus="nav:current"]').focus();
    assert.equal(await shell.getAttribute('data-sidebar-expanded'), 'true', 'keyboard focus expands labels');
    await page.locator('.wb-run-mindmap').focus();
    await page.mouse.move(1000, 800);
    await page.waitForTimeout(250);
    await page.waitForFunction(() => document.querySelector('.tapl-workbench').dataset.sidebarExpanded === 'false');
    await page.setViewportSize({ width: 1280, height: 420 });
    assert.ok(await sidebar.evaluate(el => el.scrollHeight > el.clientHeight));
    await page.locator('.wb-discard-button').scrollIntoViewIfNeeded();
    assert.ok(await page.locator('.wb-discard-button').isVisible());
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.querySelector('.wb-sidebar').inert);
    assert.equal(await pin.isVisible(), false);
    await page.locator('.wb-mobile-menu').click();
    await page.locator('[data-wb-focus="explore:PLAN"]').click();
    await page.locator('.wb-explore-panel').waitFor();
    await page.keyboard.press('Escape');
    await page.keyboard.press('Escape');
    assert.equal(await sidebar.evaluate(el => el.inert), true);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('large rail counts retain their full names and captions stay on one line throughout expansion', { timeout: 30000 }, async () => {
  const page = await browser.newPage({ viewport:{width:1440,height:1000},locale:'ko-KR' });
  try {
    await page.route('**/api/message',async route => {
      const response=await route.fetch(), payload=await response.json();
      const status=payload.view?.type==='overview' ? payload.view.status : undefined;
      if(status?.active_run && status.tasks?.length) {
        const item=status.tasks[0];
        status.tasks=Array.from({length:137},(_,i)=>({...item,id:1000+i,stable_id:`TASK-${i+1000}`,status:'Pending'}));
        status.task_counts={Pending:137};
      }
      await route.fulfill({response,json:payload});
    });
    await page.goto(origin);await page.locator('.wb-run-mindmap').waitFor();
    const task=page.locator('[data-wb-focus="nav:tasks"]');
    assert.equal(await page.locator('.wb-count-compact').count(),0);
    assert.ok((await task.getAttribute('aria-label')).includes('137개'));
    assert.equal(await task.locator('.wb-rail-count').isVisible(),false);
    await page.locator('.wb-sidebar').hover({position:{x:20,y:4}});
    const heights=await page.locator('.wb-workspace-heading .wb-nav-caption').evaluate(async el=>{
      const values=[];for(let i=0;i<24;i++){await new Promise(requestAnimationFrame);values.push({height:el.getBoundingClientRect().height,line:parseFloat(getComputedStyle(el).lineHeight),wrap:getComputedStyle(el).whiteSpace});}return values;
    });
    assert.ok(heights.every(value=>value.wrap==='nowrap' && value.height<=value.line+1),'caption never wraps during the width transition');
    assert.equal(await task.locator('.wb-count-full').innerText(),'137개');
    assert.equal(await task.locator('.wb-rail-count').isVisible(),true);
    assert.equal(await page.locator('.wb-mm-world').evaluate(el=>getComputedStyle(el).willChange),'auto');
    assert.equal(await page.locator('.wb-mm-node-button').first().evaluate(el=>getComputedStyle(el).transform),'none');
  } finally {await page.close();}
});

test('real Viewer keeps RUN context, record navigation, preferences and fixed shell', { timeout: 90000 }, async () => {
  const { page, errors } = await openPage();
  try {
    assert.equal(await page.getByRole('tab').count(), 2);
    assert.equal(await page.locator('.wb-run-facts').count(), 0);
    assert.equal(await page.locator('.wb-mm-percent').innerText(), '25%');
    assert.equal(await page.locator('[data-wb-focus="nav:current"] .wb-count-full').textContent(), '25%');
    assert.equal(await page.locator('.wb-mm-node').count(), 28);
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
    await page.locator('.wb-run-mindmap').waitFor();
    assert.equal(await page.locator('.wb-run-tab-temporary').count(), 0);
    assert.equal(await page.getByRole('tab').count(), 2);
    assert.equal(await page.locator('.wb-mm-node[data-kind=task]').count(), 1);
    assert.equal(await page.locator('.wb-mm-node[data-kind=task]').isVisible(), true);

    await page.locator('.wb-language-menu summary').click();
    await page.getByRole('button', { name: 'English', exact: true }).click();
    await page.getByRole('button', { name: 'Use dark theme', exact: true }).click();
    await page.reload();
    await page.locator('.wb-run-mindmap').waitFor();
    assert.equal(await page.locator('html').getAttribute('lang'), 'en');
    assert.equal(await page.locator('html').getAttribute('data-tapl-theme'), 'dark');
    assert.equal(await page.locator('.wb-back').count(), 0, 'reload clears historical Back');
    const picker = page.locator('.wb-workspace-heading button');
    assert.equal(await picker.count(), 1);
    assert.equal(await page.locator('.wb-workspace-switch').count(), 0, 'browser uses the heading icon');
    await picker.click();
    await page.locator('#tapl-workspace-path').waitFor();
    await page.locator('dialog.wb-workspace-dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.locator('.wb-run-mindmap').waitFor();
    assert.equal(await page.locator('.wb-mm-node[data-kind=task]').count(), 1);
    assert.equal(await page.locator('.wb-mm-node[data-kind=task]').isVisible(), true);

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
    await page.locator('.wb-run-mindmap').waitFor();
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
    await page.locator('.wb-run-mindmap').waitFor();
    assert.ok((await picker.getAttribute('title')).includes(secondWorkspace));
    assert.notEqual(await page.locator('.wb-run-tab[aria-selected="true"]').getAttribute('title'), current);
    await page.locator('[data-wb-focus="nav:tasks"]').click();
    assert.equal(await page.locator('[data-wb-focus="task-query"]').inputValue(), '');
    assert.equal(await page.locator('[data-wb-focus="filter:all"]').getAttribute('aria-pressed'), 'true');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('Current RUN is a source-safe interactive mindmap with bounded camera and pointer-only focus cleanup', { timeout: 60000 }, async () => {
  const { page, errors } = await openPage();
  try {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const map = page.locator('.wb-run-mindmap');
    const world = page.locator('.wb-mm-world');
    const camera = () => world.evaluate(el => { const m = new DOMMatrix(getComputedStyle(el).transform); return { x: m.e, y: m.f, z: m.a }; });
    assert.equal(await page.locator('.wb-mm-node').count(), 28);
    assert.equal(await page.locator('.wb-mm-edge').count(), 27);
    assert.equal(await page.locator('.wb-run-information,.wb-plan-section,.wb-active-section,.wb-flow-board').count(), 0);
    assert.equal(new Set(await page.locator('.wb-mm-node[data-kind="task"] button').evaluateAll(els => els.map(el => el.dataset.status))).size, 4);
    assert.deepEqual(await map.boundingBox(), await page.locator('.wb-page-scroll').boundingBox());
    await page.keyboard.press('Tab');
    await map.click({ position: { x: 500, y: 45 } });
    assert.equal(await map.evaluate(el => getComputedStyle(el).outlineStyle), 'none', 'pointer interaction has no canvas focus outline');
    await page.keyboard.press('Tab');
    await map.focus();
    assert.equal(await map.evaluate(el => getComputedStyle(el).outlineStyle), 'solid', 'keyboard focus remains visible');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(30);
    const before = await camera();
    await page.mouse.move(850, 150);
    await page.mouse.wheel(40, 55);
    await page.waitForTimeout(50);
    const panned = await camera();
    assert.equal(panned.z, before.z);
    assert.ok(panned.x < before.x && panned.y < before.y);
    await page.keyboard.down('Control');
    await page.mouse.wheel(0, -20);
    await page.keyboard.up('Control');
    await page.waitForTimeout(50);
    assert.ok((await camera()).z > panned.z);
    for (const direction of [1, -1]) {
      await page.mouse.wheel(direction * 1e6, direction * 1e6);
      await page.waitForTimeout(50);
      const bounded = await camera();
      assert.ok(Math.abs(bounded.x) < 2500 && Math.abs(bounded.y) < 5000, 'camera cannot leave the graph bounds');
    }
    await map.focus(); await page.keyboard.press('Escape');
    const leaf = page.locator('.wb-mm-node[data-kind="task"] button').filter({ hasText: 'TASK-013' });
    await leaf.focus(); await page.waitForTimeout(30);
    const position = await camera();
    await leaf.click({ force: true });
    await page.locator('.wb-record-page').waitFor();
    assert.equal(await page.locator('.wb-record-page h1').innerText(), 'Interface task 13');
    await page.locator('.wb-back').click(); await map.waitFor();
    await page.waitForTimeout(30);
    const returned = await camera();
    assert.ok(Math.abs(position.x-returned.x)<1 && Math.abs(position.y-returned.y)<1, 'return restores the RUN camera');
    for (const locale of ['ko','en']) {
      await page.setViewportSize({ width:1440, height:1000 });
      await page.locator('.wb-language-menu summary').click();
      await page.getByRole('button',{name:locale==='ko'?'한국어':'English',exact:true}).click();
      for (const theme of ['light','dark']) {
        if(await page.locator('html').getAttribute('data-tapl-theme')!==theme) await page.locator('[data-wb-focus="theme-toggle"]').click();
        for (const width of [1440,390]) {
          await page.setViewportSize({ width,height:1000 });
          await page.waitForTimeout(50);
          assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
          assert.deepEqual(await map.boundingBox(),await page.locator('.wb-page-scroll').boundingBox());
          await shot(page,`mindmap-${locale}-${theme}-${width}`);
        }
      }
    }
    assert.deepEqual(errors,[]);
  } finally { await page.close(); }
});

test('associative memories branch left to right with shared cues, exact sources and a persistent gesture camera', { timeout: 60000 }, async () => {
  const { page, errors } = await openPage();
  try {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.locator('[data-wb-focus="nav:memories"]').click();
    const map = page.locator('.wb-memory-mindmap');
    await map.waitFor();
    await page.mouse.move(1300, 100);
    const world = map.locator('.wb-mm-world');
    const camera = () => world.evaluate(el => { const m = new DOMMatrix(getComputedStyle(el).transform); return { x:m.e,y:m.f,z:m.a }; });
    assert.equal(await map.locator('[data-kind=source]').count(),2);
    assert.equal(await map.locator('[data-kind=memory]').count(),2);
    assert.equal(await map.locator('[data-kind=cue]').count(),5);
    assert.equal(await map.locator('g[data-relation]').count(),8);
    assert.equal(await page.locator('.wb-memory-card').count(),0);
    const edges = await map.evaluate(el => [...el.querySelectorAll('g[data-from]')].map(edge => {
      const from = [...el.querySelectorAll('[data-mindmap-node]')].find(n => n.dataset.mindmapNode===edge.dataset.from);
      const to = [...el.querySelectorAll('[data-mindmap-node]')].find(n => n.dataset.mindmapNode===edge.dataset.to);
      return {from:from.getBoundingClientRect().right,to:to.getBoundingClientRect().left};
    }));
    assert.ok(edges.every(edge=>edge.to>edge.from),'every recorded relationship flows left to right');
    const cue = map.locator('[data-kind=cue] button').filter({hasText:'interface evidence'});
    await cue.hover();
    assert.equal(await map.locator('[data-kind=memory].wb-mm-emphasis').count(),2,'shared cue highlights both related memories');
    assert.equal(await map.locator('[data-kind=source].wb-mm-emphasis').count(),2);
    await cue.click();
    await page.waitForFunction(()=>document.querySelector('.wb-memory-mindmap')?.dataset.memoryCameraKey.includes('interface evidence'));
    assert.equal(await map.locator('[data-kind=memory]').count(),2);
    await page.mouse.move(850,450); await page.mouse.wheel(45,55); await page.waitForTimeout(50);
    const panned=await camera();
    await page.keyboard.down('Control'); await page.mouse.wheel(0,-25); await page.keyboard.up('Control');
    await page.waitForTimeout(50);
    assert.ok((await camera()).z>panned.z,'pinch zoom is distinct from ordinary pan');
    const memory=map.locator('[data-kind=memory] button').filter({hasText:'original contrast finding'});
    await memory.focus(); await page.waitForTimeout(50);
    const prior=await camera();
    await memory.click({force:true}); await page.locator('.wb-memory-source-preview').waitFor();
    await page.locator('.wb-back').click(); await map.waitFor(); await page.waitForTimeout(50);
    const returned=await camera();
    assert.ok(Math.abs(prior.x-returned.x)<1 && Math.abs(prior.y-returned.y)<1 && Math.abs(prior.z-returned.z)<0.001);
    const source=map.locator('[data-kind=source] button').filter({hasText:'Archived contrast finding'});
    await source.focus(); await source.click({force:true}); await page.locator('.wb-record-page').waitFor();
    assert.equal(await page.locator('.wb-record-page h1').innerText(),'Archived contrast finding');
    assert.equal(await page.locator('.wb-run-tab-temporary').count(),1);
    await page.locator('.wb-back').click(); await map.waitFor();
    for (const locale of ['ko','en']) {
      await page.setViewportSize({width:1440,height:1000});
      await page.locator('.wb-language-menu summary').click();
      await page.getByRole('button',{name:locale==='ko'?'한국어':'English',exact:true}).click();
      for (const theme of ['light','dark']) {
        if(await page.locator('html').getAttribute('data-tapl-theme')!==theme) await page.locator('[data-wb-focus="theme-toggle"]').click();
        for (const [width,height] of [[1440,1000],[390,740],[1100,500]]) {
          await page.setViewportSize({width,height}); await page.waitForTimeout(80);
          assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
          assert.ok((await map.boundingBox()).height>=250,'graph keeps an operable viewport');
          await page.locator('.wb-secondary-pagination').scrollIntoViewIfNeeded();
          const pager=await page.locator('.wb-secondary-pagination').boundingBox();
          assert.ok(pager.y+pager.height<=height+1,'pagination remains reachable on short screens');
          await page.locator('.wb-page-scroll').evaluate(el=>el.scrollTop=0);
          await shot(page,`memory-map-${locale}-${theme}-${width}x${height}`);
        }
      }
    }
    assert.deepEqual(errors,[]);
  } finally {await page.close();}
});

test('memory graph search and pagination retain the query and return to first-page cue results', { timeout: 30000 }, async () => {
  const {page,errors}=await openPage();
  const requests=[];
  await page.route('**/api/message',async route=>{
    const request=route.request().postDataJSON();
    if(request.command!=='memories') return route.continue();
    requests.push(request);
    const response=await route.fetch(); const payload=await response.json();
    const offset=request.offset||0;
    payload.view={...payload.view,offset,limit:1,memories:payload.view.memories.slice(0,1)};
    return route.fulfill({response,json:payload});
  });
  try {
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.locator('[data-wb-focus="nav:memories"]').click();
    const map=page.locator('.wb-memory-mindmap'); await map.waitFor();
    await page.locator('[data-wb-focus="memory-query"]').fill('interface evidence');
    await page.locator('[data-wb-focus="memory-submit"]').click();
    await page.waitForFunction(()=>document.querySelector('.wb-memory-mindmap')?.dataset.memoryCameraKey.includes('interface evidence'));
    await page.locator('.wb-secondary-pagination button').last().click();
    await page.waitForFunction(()=>document.querySelector('.wb-search-context')?.textContent.includes('2–2'));
    assert.equal(requests.at(-1).query,'interface evidence'); assert.equal(requests.at(-1).offset,1);
    assert.equal(await map.locator('[data-kind=memory]').count(),1);
    assert.equal(await map.locator('[data-kind=source]').count(),1,'only this page creates relationships');
    await map.locator('[data-kind=cue] button').filter({hasText:'interface evidence'}).click();
    await page.waitForFunction(()=>document.querySelector('.wb-search-context')?.textContent.includes('1–1'));
    assert.equal(requests.at(-1).offset,0);
    assert.equal(requests.at(-1).query,'interface evidence');
    await page.locator('[data-wb-focus="memory-query"]').fill('zzzxqptnoresult980');
    await page.locator('[data-wb-focus="memory-submit"]').click();
    await page.getByRole('button',{name:'검색 초기화',exact:true}).waitFor();
    assert.equal(await map.count(),0);
    assert.deepEqual(errors,[]);
  } finally {await page.close();}
});

test('PLAN, FINDING, memories and diagnostics use reading pages and nested vertical fields', { timeout: 45000 }, async () => {
  const { page, errors } = await openPage();
  try {
    await page.locator('.wb-mm-node[data-kind=plan] button').first().click({ force:true });
    await page.locator('.wb-record-page').waitFor();
    assert.equal(await page.locator('.wb-reading-section h2').filter({ hasText: '목적' }).count(), 1);
    assert.equal(await page.locator('.wb-reading-section h2').filter({ hasText: '요구사항' }).count(), 1);
    assert.equal(await page.locator('.wb-reading-section h2').filter({ hasText: /^내용$/ }).count(), 0);
    assert.equal(await page.getByText('Legacy PLAN body repeats the structured fields.', { exact: false }).isVisible(), false);
    const additional = page.locator('.wb-record-disclosures > details').first();
    await additional.locator('summary').first().click();
    assert.equal(await page.getByText('Legacy PLAN body repeats the structured fields.', { exact: false }).isVisible(), true);
    await shot(page, 'plan-detail-ko-light');
    await page.locator('.wb-back').click();
    await page.locator('[data-wb-focus="explore:FINDING"]').click();
    await page.locator('.wb-fold-list button').first().click();
    await page.locator('.wb-record-page').waitFor();
    assert.equal(await page.evaluate(() => window.untrusted), undefined);
    assert.ok((await page.locator('.wb-record-page').innerText()).includes('<script>window.untrusted = true</script>'));
    await shot(page, 'finding-detail-ko-light');
    await page.locator('[data-wb-focus="nav:memories"]').click();
    await page.locator('.wb-memory-mindmap [data-kind=memory]').first().waitFor();
    assert.equal(await page.locator('.wb-memory-mindmap [data-kind=memory]').count(), 2);
    assert.equal(await page.locator('.tapl-memory-list,.tapl-card').count(), 0);
    await shot(page, 'memories-ko-light');
    await page.locator('.wb-memory-mindmap [data-kind=memory]').filter({ hasText: 'original contrast finding' }).locator('button').click();
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
    await page.locator('.wb-sidebar').hover({ position: { x: 20, y: 5 } });
    await page.waitForTimeout(350);
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
    await page.locator('[data-wb-focus="nav:tasks"]').click();
    const colors = () => page.locator('.wb-tasks-table .wb-status-label').evaluateAll(elements => elements.map(el => getComputedStyle(el).color));
    assert.equal(new Set(await colors()).size, 4);
    await page.locator('[data-wb-focus="theme-toggle"]').click();
    await page.waitForFunction(() => document.documentElement.dataset.taplTheme === 'dark');
    assert.equal(new Set(await colors()).size, 4);
    await page.locator('[data-wb-focus="nav:current"]').click();
    await page.mouse.move(1000,800);
    await page.waitForFunction(() => document.querySelector('.tapl-workbench').dataset.sidebarExpanded === 'false');
    await shot(page, 'current-ko-dark');
    await page.locator('.wb-mm-node[data-kind=task] button').first().focus();
    await page.locator('.wb-mm-node[data-kind=task] button').first().click();
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
    await page.locator('.wb-run-mindmap').waitFor();
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
    await page.locator('.wb-run-mindmap').waitFor();
    unsupportedMemory = true;
    await page.locator('[data-wb-focus="nav:memories"]').click();
    await page.locator('.wb-empty').waitFor();
    assert.equal(await page.locator('.wb-memory-mindmap').count(), 0);
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
    await page.locator('.wb-run-mindmap').waitFor();
  } finally { release(); await page.close(); }
});

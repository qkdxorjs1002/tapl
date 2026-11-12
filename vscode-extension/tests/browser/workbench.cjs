const { test, before, beforeEach, after } = require('node:test');
const assert = require('node:assert/strict');
const { spawn, spawnSync } = require('node:child_process');
const { mkdtempSync, mkdirSync, rmSync, readFileSync, writeFileSync } = require('node:fs');
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
beforeEach(() => {
  // Display preferences now belong to the shared fixture config, not each page's storage.
  for (const folder of [workspace, secondWorkspace]) {
    const result = spawnSync(python, ['-c', 'import sys; from pathlib import Path; from taplctl.settings import SettingsService; s=SettingsService(Path(sys.argv[1])); d=s.get(); s.save({"viewer.language":"auto","viewer.layout":"auto"}, d["revision"])', folder], { encoding: 'utf8', env: { ...process.env, PYTHONPATH: path.resolve(__dirname, '../../../tapl') } });
    assert.equal(result.status, 0, result.stderr);
  }
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

async function setLanguage(page, locale) {
  await page.locator('[data-wb-focus="nav:settings"]').click();
  const language = page.locator('[id="setting-viewer.language"]'); await language.waitFor();
  if (await language.inputValue() !== locale) {
    await language.selectOption(locale);
    await page.locator('.wb-settings-savebar button[type=submit]').click();
    await page.waitForFunction(expected => document.documentElement.lang === expected, locale);
  }
  await page.locator('.wb-settings .wb-back').click();
}

test('settings edits all CLI sections, saves model/profile changes together, and confirms reset', { timeout: 60000 }, async () => {
  const { page, errors } = await openPage();
  const configPath = path.join(workspace, '.tapl/config.toml');
  const readSettings = () => {
    const result = spawnSync(python, ['-c', 'import json,sys; from pathlib import Path; from taplctl.settings import SettingsService; print(json.dumps(SettingsService(Path(sys.argv[1])).get()))', workspace], { encoding: 'utf8', env: { ...process.env, PYTHONPATH: path.resolve(__dirname, '../../../tapl') } });
    assert.equal(result.status, 0, result.stderr); return JSON.parse(result.stdout);
  };
  try {
    await page.locator('[data-wb-focus="nav:settings"]').click();
    await page.locator('[id="setting-search.max_results"]').waitFor();
    await page.mouse.move(1400, 30); await page.waitForTimeout(650);
    assert.equal(await page.locator('.wb-topbar .wb-language-menu').count(), 0);
    assert.equal(await page.locator('.wb-settings-field-copy > label').count(), 23);
    await page.locator('[id="setting-viewer.language"]').selectOption('en');
    await page.locator('.wb-settings-savebar button[type=submit]').click();
    await page.waitForFunction(() => document.documentElement.lang === 'en');
    const field = key => page.locator(`[id="setting-${key}"]`);
    await field('workflow.authoring_detail').selectOption('normal');
    await field('recall.enabled').uncheck();
    await field('search.mode').selectOption('bm25');
    await field('search.max_results').fill('27');
    await field('search.hybrid_semantic_ratio').fill('0.4');
    await field('search.semantic_provider').selectOption('local');
    await field('search.searchd_model_idle_timeout_seconds').fill('0');
    const origins = field('viewer.allowed_origins');
    await origins.getByRole('button', { name: /Add entry/ }).click();
    await origins.locator('input').fill('https://settings.example.invalid');
    await field('subagents.setup_complete').check();
    await field('subagents.preference').fill('Keep independent verification.');
    const models = field('subagents.models');
    await models.getByRole('button', { name: /Add model/ }).click();
    await models.getByLabel('Model ID', { exact: true }).fill('qa-model.with.dot');
    await models.getByRole('button', { name: /Add entry/ }).click();
    await models.locator('.wb-settings-list input').fill('high');
    const profile = field('subagents.profiles').locator('.wb-settings-repeater').first();
    await profile.getByRole('button', { name: /Add candidate/ }).click();
    await profile.locator('.wb-settings-candidate input').nth(0).fill('qa-model.with.dot');
    await profile.locator('.wb-settings-candidate input').nth(1).fill('high');
    const claude = field('clients.claude-code.subagents.models');
    await claude.getByRole('button', { name: /Add model/ }).click();
    await claude.getByLabel('Model ID', { exact: true }).fill('inherit');
    await field('clients.claude-code.subagents.setup_complete').check();
    await field('clients.claude-code.subagents.strategy').selectOption('balanced');
    await page.locator('.wb-settings-savebar button[type=submit]').click();
    await page.getByText('Configuration saved.', { exact: true }).waitFor();
    const saved = readSettings();
    assert.equal(saved.values['search.max_results'], 27);
    assert.equal(saved.values['recall.enabled'], false);
    assert.deepEqual(saved.values['subagents.models'], { 'qa-model.with.dot': ['high'] });
    assert.deepEqual(saved.values['subagents.profiles'][0].candidates, [{ model: 'qa-model.with.dot', reasoning_effort: 'high' }]);
    assert.deepEqual(saved.values['clients.claude-code.subagents.models'], { inherit: [] });
    const prior = readFileSync(configPath, 'utf8');
    await page.getByRole('button', { name: 'Reset all to defaults', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
    assert.equal(readFileSync(configPath, 'utf8'), prior);
    await page.getByRole('button', { name: 'Reset all to defaults', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Reset configuration', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('setting-viewer.language').value === 'auto');
    const reset = readSettings(); assert.deepEqual(reset.values, reset.defaults); assert.deepEqual(reset.overrides, []);
    assert.match(readFileSync(configPath, 'utf8'), /# Isolated Viewer fixture/); assert.match(readFileSync(configPath, 'utf8'), /keep = "fixture"/);
    assert.equal(await field('viewer.language').inputValue(), 'auto');
    await page.reload(); await page.locator('.wb-run-mindmap').waitFor();
    assert.equal(await page.locator('html').getAttribute('lang'), 'ko');
    await page.locator('[data-wb-focus="nav:settings"]').click(); await field('search.max_results').waitFor();
    assert.equal(await field('search.max_results').inputValue(), '12');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('settings retains invalid and conflicting drafts, restores pages, and keeps controls in short viewports', { timeout: 45000 }, async () => {
  const { page, errors } = await openPage();
  try {
    await page.locator('[data-wb-focus="nav:settings"]').click();
    const input = page.locator('[id="setting-search.max_results"]'); await input.waitFor();
    await page.mouse.move(1400, 30); await page.waitForTimeout(650);
    await input.fill('0'); assert.equal(await page.locator('.wb-settings-savebar button[type=submit]').isDisabled(), true);
    assert.equal(await input.getAttribute('aria-invalid'), 'true');
    await input.fill('25');
    await page.locator('[data-wb-focus="nav:tasks"]').click(); await page.locator('.wb-tasks-table').waitFor();
    await page.locator('[data-wb-focus="nav:settings"]').click(); assert.equal(await input.inputValue(), '25');
    const configPath = path.join(workspace, '.tapl/config.toml');
    writeFileSync(configPath, readFileSync(configPath, 'utf8')+'\n# changed in another editor\n');
    await page.locator('.wb-settings-savebar button[type=submit]').click();
    await page.locator('.wb-settings-error').waitFor(); assert.equal(await input.inputValue(), '25');
    await page.locator('.wb-settings-error button').click();
    await page.getByRole('dialog').getByRole('button').first().click(); assert.equal(await input.inputValue(), '25');
    await page.locator('.wb-settings-error button').click(); await page.getByRole('dialog').getByRole('button').last().click();
    await page.waitForFunction(() => document.getElementById('setting-search.max_results').value === '12');
    for (const locale of ['en', 'ko']) {
      const language = page.locator('[id="setting-viewer.language"]'); await language.waitFor();
      if (await language.inputValue() !== locale) {
        await language.selectOption(locale);
        await page.locator('.wb-settings-savebar button[type=submit]').click();
        await page.waitForFunction(expected => document.documentElement.lang === expected, locale);
      }
      for (const theme of ['light', 'dark']) {
        if (await page.locator('html').getAttribute('data-tapl-theme') !== theme) await page.locator('[data-wb-focus="theme-toggle"]').click();
        for (const [width, height] of [[1440, 1000], [1100, 420], [390, 740]]) {
          await page.setViewportSize({ width, height }); await page.mouse.move(width-10, 30); await page.waitForTimeout(100);
          await page.locator('.wb-page-scroll').evaluate(el => el.scrollTop=0);
          const bar = await page.locator('.wb-settings-savebar').boundingBox();
          assert.ok(bar.y >= 72 && bar.y+bar.height <= height, `visible Save controls: ${width}x${height}`);
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
          await shot(page, `settings-${locale}-${theme}-${width}x${height}`);
        }
      }
      await page.setViewportSize({ width: 1440, height: 1000 });
    }
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('settings works without an active RUN and keeps unsaved inputs through background hydration', { timeout: 30000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, locale: 'ko-KR' });
  let overview;
  await page.route('**/api/message', async route => {
    const response = await route.fetch(), payload = await response.json();
    if (payload.view?.type === 'overview') {
      Object.assign(payload.view.status, { active_run: null, active_runs: [], plans: [], tasks: [], findings: [], task_counts: {} });
      overview = structuredClone(payload);
    }
    await route.fulfill({ response, json: payload });
  });
  try {
    await page.goto(origin); await page.waitForLoadState('networkidle');
    await page.locator('[data-wb-focus="nav:settings"]').click();
    const input = page.locator('[id="setting-search.max_results"]'); await input.waitFor(); await input.fill('19');
    await page.evaluate(payload => window.postMessage({ ...payload, type: 'view:update' }, '*'), overview);
    assert.equal(await input.inputValue(), '19');
    assert.equal(await page.locator('[data-wb-focus="nav:settings"]').getAttribute('aria-current'), 'page');
    assert.equal(await page.locator('.wb-settings-field-copy > label').count(), 23);
  } finally { await page.close(); }
});

test('glass flow follows executing paths, highlights related tubes without restarting, and stops on status refresh', { timeout: 45000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'ko-KR' });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  let overview;
  await page.route('**/api/message', async route => {
    const response = await route.fetch(), payload = await response.json();
    if (payload.view?.type === 'overview') {
      if (!overview) {
        const s = payload.view.status, plan = s.plans[0], task = s.tasks[0];
        s.active_run.status = 'active';
        s.plans = [1, 2].map(i => ({ ...plan, id: 90000+i, stable_id: `PLAN-90${i}`, status: 'Finalized', title: `Flow plan ${i}` }));
        s.tasks = ['In Progress', 'Completed', 'Blocked', 'Pending', 'In Progress'].map((status, i) => ({
          ...task, id: 91001+i, stable_id: `TASK-90${i+1}`, status, title: `Flow task ${i+1}`,
          spec_id: i === 4 ? null : s.plans[i === 3 ? 1 : 0].stable_id
        }));
        s.task_counts = { 'In Progress': 2, Completed: 1, Blocked: 1, Pending: 1 };
        overview = structuredClone(payload);
      } else if (payload.view.status.active_run?.id === overview.view.status.active_run.id) {
        payload.view.status = structuredClone(overview.view.status);
      }
    }
    await route.fulfill({ response, json: payload });
  });
  const publish = async () => page.evaluate(payload => window.postMessage({ ...payload, type: 'view:update' }, '*'), overview);
  try {
    await page.goto(origin); await page.waitForLoadState('networkidle');
    const map = page.locator('.wb-run-mindmap'); await map.waitFor();
    await page.mouse.move(1400, 30);
    await page.waitForFunction(() => document.querySelectorAll('.wb-mm-flow').length === 3);
    const activeKeys = await map.locator('g[data-flow=running]').evaluateAll(groups => groups.map(group =>
      JSON.parse(group.dataset.to).find(value => typeof value === 'string' && /^(PLAN|TASK)-/.test(value))).sort());
    assert.deepEqual(activeKeys, ['PLAN-901', 'TASK-901', 'TASK-905']);
    const follow = map.locator('.wb-mm-follow');
    assert.equal(await follow.getAttribute('aria-pressed'), 'true');
    assert.equal(await map.locator('g[data-flow=running].wb-mm-edge-active').count(), 3, 'following highlights every executing ancestor path');
    assert.equal(await map.locator('[data-kind=task].wb-mm-emphasis').count(), 2);
    assert.equal(await map.locator('[data-kind=task].wb-mm-dim').count(), 3, 'fitted PLAN does not highlight idle siblings');
    const idlePulses = () => map.locator('g[data-to]:not([data-flow]) > .wb-mm-pulse').evaluateAll(nodes => nodes.every(node => +getComputedStyle(node).opacity === 0));
    assert.ok(await idlePulses());
    const flow = map.locator('.wb-mm-flow').first();
    const before = await flow.evaluate(node => node.style.getPropertyValue('--mm-flow-progress'));
    const beforeDash = await flow.locator('.wb-mm-flow-core').evaluate(node => getComputedStyle(node).strokeDashoffset);
    await page.waitForTimeout(100);
    assert.notEqual(await flow.evaluate(node => node.style.getPropertyValue('--mm-flow-progress')), before);
    assert.notEqual(await flow.locator('.wb-mm-flow-core').evaluate(node => getComputedStyle(node).strokeDashoffset), beforeDash, 'the light travels along the tube');
    await map.locator('[data-kind=task] button').filter({ hasText: 'Flow task 2' }).hover();
    await page.waitForTimeout(300);
    assert.equal(await map.locator('g[data-flow=running]').count(), 3, 'hovering a completed task does not start its flow');
    assert.ok((await map.locator('g[data-flow=running][data-to*="TASK-901"]').getAttribute('class')).includes('wb-mm-edge-dim'), 'direct hover takes priority over automatic highlight');
    assert.ok(await idlePulses());
    assert.ok(await map.locator('g[data-flow=running]').evaluateAll(groups => groups.every(group => {
      const d = group.querySelector('.wb-mm-edge').getAttribute('d');
      return [...group.querySelectorAll('.wb-mm-glass-path')].every(path => path.getAttribute('d') === d);
    })), 'tube and light follow the displaced curve together');
    await page.mouse.move(1400, 30); await page.waitForTimeout(700);
    assert.equal(await map.locator('g[data-flow=running].wb-mm-edge-active').count(), 3, 'leaving restores automatic highlight');
    await map.locator('[data-kind=task] button').filter({ hasText: 'Flow task 2' }).focus();
    assert.equal(await map.locator('[data-kind=task].wb-mm-emphasis').count(), 1, 'direct focus takes priority');
    await map.focus();
    assert.equal(await map.locator('g[data-flow=running].wb-mm-edge-active').count(), 3, 'leaving focus restores automatic highlight');
    await follow.click();
    assert.equal(await map.locator('.wb-mm-emphasis, .wb-mm-edge-active, .wb-mm-dim, .wb-mm-edge-dim').count(), 0, 'OFF clears automatic highlight');
    const runningTask = map.locator('g[data-flow=running][data-to*="TASK-901"]');
    const taskButton = map.locator('[data-kind=task] button').filter({ hasText: 'Flow task 1' });
    const tubeStyle = () => runningTask.evaluate(group => {
      const style = selector => getComputedStyle(group.querySelector(selector));
      return { stroke: style('.wb-mm-edge').stroke, width: parseFloat(style('.wb-mm-edge').strokeWidth),
        glow: style('.wb-mm-flow-glow').stroke, glowWidth: parseFloat(style('.wb-mm-flow-glow').strokeWidth),
        reflection: +style('.wb-mm-tube-reflection').strokeOpacity };
    });
    for (const theme of ['dark', 'light']) {
      await page.evaluate(theme => document.documentElement.dataset.taplTheme = theme, theme);
      await page.waitForTimeout(300); await shot(page, `glass-flow-${theme}`);
      const baseline = await tubeStyle();
      const pulse = runningTask.locator('.wb-mm-flow');
      const progress = await pulse.evaluate(node => { node.__retainedFlow = true; return node.style.getPropertyValue('--mm-flow-progress'); });
      await taskButton.hover(); await page.waitForTimeout(300);
      const highlighted = await tubeStyle();
      assert.notEqual(highlighted.stroke, baseline.stroke, `${theme} running tube uses related emphasis`);
      assert.ok(highlighted.width > baseline.width && highlighted.glowWidth > baseline.glowWidth);
      assert.notEqual(highlighted.glow, baseline.glow, 'travelling light inherits the same emphasis');
      assert.ok(highlighted.reflection > baseline.reflection);
      assert.ok(await pulse.evaluate(node => node.__retainedFlow), 'emphasis retains the flowing element');
      assert.notEqual(await pulse.evaluate(node => node.style.getPropertyValue('--mm-flow-progress')), progress, 'flow continues while highlighted');
      assert.equal(await map.locator('g[data-flow=running]').count(), 3); assert.ok(await idlePulses());
      assert.ok((await map.locator('g[data-flow=running][data-to*="TASK-905"]').getAttribute('class')).includes('wb-mm-edge-dim'));
      await shot(page, `glass-flow-highlight-${theme}`);
      await page.mouse.move(1400, 30); await page.waitForTimeout(300);
      assert.equal((await tubeStyle()).stroke, baseline.stroke, 'leaving restores the ordinary running tube');
    }
    for (const mode of ['vscode-high-contrast', 'vscode-high-contrast-light']) {
      await page.evaluate(mode => {
        delete document.documentElement.dataset.taplTheme; document.body.className = mode;
        document.body.style.setProperty('--vscode-textLink-foreground', '#ffff00');
      }, mode);
      await map.focus(); await page.waitForTimeout(300); const baseline = await tubeStyle();
      await taskButton.focus(); await page.waitForTimeout(300);
      assert.notEqual((await tubeStyle()).stroke, baseline.stroke, `${mode} keyboard focus highlights the tube`);
      assert.equal(await runningTask.locator('.wb-mm-flow-glow').evaluate(node => getComputedStyle(node).display), 'none');
      await map.focus();
    }
    await page.evaluate(() => { document.body.className = ''; document.body.style.removeProperty('--vscode-textLink-foreground'); document.documentElement.dataset.taplTheme = 'light'; });
    await page.emulateMedia({ reducedMotion: 'reduce' }); await page.waitForTimeout(100);
    assert.ok(await map.locator('.wb-mm-flow, .wb-mm-pulse').evaluateAll(nodes => nodes.every(node => getComputedStyle(node).display === 'none')));
    const stopped = await flow.evaluate(node => node.style.getPropertyValue('--mm-flow-progress'));
    await page.waitForTimeout(150);
    assert.equal(await flow.evaluate(node => node.style.getPropertyValue('--mm-flow-progress')), stopped);
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    overview.view.status.tasks.forEach(task => { task.status = 'Completed'; });
    overview.view.status.task_counts = { Completed: 5 }; await publish();
    await page.waitForFunction(() => document.querySelectorAll('.wb-mm-flow').length === 0);
    assert.ok(await map.locator('.wb-mm-pulse').evaluateAll(nodes => nodes.every(node => +getComputedStyle(node).opacity === 0)), 'completed paths leave no stale light');
    await follow.click();
    assert.equal(await map.locator('.wb-mm-emphasis').count(), 0, 'no executing targets means no automatic highlight');
    overview.view.status.plans[0].status = 'In Progress'; await publish();
    await page.waitForFunction(() => document.querySelectorAll('.wb-run-mindmap [data-kind=plan].wb-mm-emphasis').length === 1);
    assert.equal(await map.locator('[data-kind=task].wb-mm-emphasis').count(), 0, 'PLAN fallback highlights ancestors without its idle descendants');
    overview.view.status.tasks[0].status = 'In Progress'; await publish();
    await page.waitForFunction(() => document.querySelectorAll('.wb-mm-flow').length === 2);
    assert.equal(await map.locator('[data-kind=task].wb-mm-emphasis').count(), 1, 'new executing TASK refreshes automatic highlight');
    overview.view.status.active_run.status = 'archived'; await publish();
    await page.waitForFunction(() => document.querySelectorAll('.wb-mm-flow').length === 0);
    assert.equal(await map.locator('.wb-mm-emphasis, .wb-mm-edge-active').count(), 0, 'ended RUN has no automatic highlight');
    await page.locator('[data-wb-focus="nav:memories"]').click(); await page.locator('.wb-memory-mindmap').waitFor();
    assert.equal(await page.locator('.wb-memory-mindmap .wb-mm-flow').count(), 0);
    assert.ok(await page.locator('.wb-memory-mindmap .wb-mm-pulse').evaluateAll(nodes => nodes.every(node => +getComputedStyle(node).opacity === 0)), 'active memories are not executing work');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('large maps bound idle work, retain keyboard targets and refresh current graph geometry', { timeout: 60000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'ko-KR' });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  let overview, memoryOverview;
  await page.addInitScript(() => {
    window.__mapSetups = 0;
    const Observer = window.ResizeObserver;
    window.ResizeObserver = class extends Observer {
      observe(target, options) { if (target.matches('.wb-mindmap')) window.__mapSetups++; return super.observe(target, options); }
    };
  });
  await page.route('**/api/message', async route => {
    const response = await route.fetch(), payload = await response.json();
    if (payload.view?.type === 'overview') {
      const s = payload.view.status, plan = s.plans[0], task = s.tasks[0];
      s.plans = Array.from({ length: 40 }, (_, i) => ({ ...plan, id: 100000+i, stable_id: `PLAN-${i+1}`, title: `Large plan ${i+1}`, status: 'Finalized' }));
      s.tasks = Array.from({ length: 1000 }, (_, i) => ({ ...task, id: 200000+i, stable_id: `TASK-${i+1}`, title: `Large task ${i+1}`, spec_id: s.plans[i%40].stable_id, status: 'Pending' }));
      s.task_counts = { Pending: 1000 }; overview = structuredClone(payload);
    }
    if (payload.view?.type === 'memories' && payload.view.memories.length) {
      const sample = payload.view.memories[0];
      payload.view.memories = Array.from({ length: 50 }, (_, i) => ({ ...sample, id: `large-memory-${i}`, source: { ...sample.source, run_id: `large-source-${i}`, title: `Large source ${i}` }, source_available: false, cue: Array.from({ length: 16 }, (_, j) => `cue ${i}-${j}`) }));
      payload.view.total = 50; payload.view.limit = 50;
      memoryOverview = structuredClone(payload);
    }
    await route.fulfill({ response, json: payload });
  });
  const idleWrites = () => page.locator('.wb-mindmap').evaluate(async host => {
    const counts = { node: 0, path: 0, pulse: 0, world: 0, light: 0 };
    const selectors = { node: '.wb-mm-node', path: '.wb-mm-edge, .wb-mm-glass-path', pulse: '.wb-mm-pulse, .wb-mm-flow', world: '.wb-mm-world', light: '.wb-mm-pointer-light' };
    const observer = new MutationObserver(records => {
      for (const { target } of records) for (const [key, selector] of Object.entries(selectors)) {
        if (target.matches(selector)) { counts[key]++; break; }
      }
    });
    observer.observe(host, { attributes: true, subtree: true, attributeFilter: ['style', 'd', 'cx', 'cy'] });
    await new Promise(resolve => setTimeout(resolve, 450)); observer.disconnect(); return counts;
  });
  try {
    await page.goto(origin); await page.waitForLoadState('networkidle'); await page.locator('.wb-run-mindmap').waitFor();
    for (const [kind, count] of [['run', 1041], ['memory', 901]]) {
      if (kind === 'memory') { await page.locator('[data-wb-focus="nav:memories"]').click(); await page.locator('.wb-memory-mindmap').waitFor(); }
      await page.mouse.move(1400, 40); await page.waitForTimeout(1000);
      const map = page.locator('.wb-mindmap');
      assert.equal(await map.locator('[data-mindmap-node]').count(), count, 'every keyboard target stays mounted');
      const writes = await idleWrites();
      assert.equal(writes.node+writes.path+writes.world+writes.light, 0, `${kind}: settled geometry sleeps`);
      assert.equal(writes.pulse, 0, `${kind}: no executing work means no ambient flow writes`);
      const pulses = await map.locator('.wb-mm-pulse').evaluateAll(nodes => nodes.filter(node => +getComputedStyle(node).opacity > 0).length);
      assert.equal(pulses, 0, 'pending work and memories remain static');
      const setups = await page.evaluate(() => window.__mapSetups);
      assert.ok(setups > 0, 'viewport setup instrumentation is active');
      await page.evaluate(async ({ payload, kind }) => {
        for (let i = 0; i < 3; i++) {
          window.postMessage({ ...structuredClone(payload), type: 'view:update' }, '*');
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }
        if (kind === 'run') {
          payload.view.status.tasks[0].body = 'Fresh record body';
          payload.view.status.tasks[0].title = 'Fresh task title';
        }
        else payload.view.memories[0].note = 'Fresh memory note';
        window.postMessage({ ...payload, type: 'view:update' }, '*');
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      }, { payload: structuredClone(kind === 'run' ? overview : memoryOverview), kind });
      assert.equal(await page.evaluate(() => window.__mapSetups), setups, `${kind}: identical and detail-only updates reuse viewport geometry`);
      assert.ok((await map.textContent()).includes(kind === 'run' ? 'Fresh task title' : 'Fresh memory note'), 'record content stays fresh while geometry is reused');
      await page.emulateMedia({ reducedMotion: 'reduce' }); await page.waitForTimeout(100);
      assert.deepEqual(await idleWrites(), { node: 0, path: 0, pulse: 0, world: 0, light: 0 });
      const last = map.locator('[data-kind=task] button, [data-kind=cue] button').last();
      await last.focus(); await page.waitForTimeout(60);
      const target = await last.boundingBox(), viewport = await map.boundingBox();
      assert.ok(target.x >= viewport.x && target.x+target.width <= viewport.x+viewport.width+1);
      assert.ok(target.y >= viewport.y && target.y+target.height <= viewport.y+viewport.height+1);
      if (kind === 'run') {
        // A polling snapshot moves retained keys; old cleanup must not restore their old coordinates.
        const next = structuredClone(overview), s = next.view.status;
        s.tasks = s.tasks.slice(0, 200); s.task_counts = { Pending: 200 };
        const source = require('esbuild').buildSync({ entryPoints: [path.resolve(__dirname, '../../src/webview/workbench/mindmap.ts')], bundle: true, platform: 'node', format: 'cjs', write: false }).outputFiles[0].text;
        const compiled = { exports: {} }; new Function('module', 'exports', source)(compiled, compiled.exports);
        const graph = compiled.exports.buildRunMindmap({ ...s, run: { ...s.active_run, source_db: s.active_run.source_db ?? s.source_db }, readonly: false });
        await page.evaluate(payload => window.postMessage({ ...payload, type: 'view:update' }, '*'), next);
        await page.waitForFunction(() => document.querySelectorAll('.wb-run-mindmap [data-mindmap-node]').length === 241); await page.waitForTimeout(60);
        const actual = await map.locator('[data-mindmap-node]').evaluateAll(nodes => nodes.map(node => {
          const m = new DOMMatrix(getComputedStyle(node).transform);
          return { key: node.dataset.mindmapNode, x: m.e+node.offsetWidth/2, y: m.f+node.offsetHeight/2 };
        }));
        const expected = new Map(graph.nodes.map(node => [node.key, node]));
        for (const node of actual) assert.ok(Math.abs(node.x-expected.get(node.key).x)<.01 && Math.abs(node.y-expected.get(node.key).y)<.01, 'current graph positions survive effect replacement');
      }
      await page.emulateMedia({ reducedMotion: 'no-preference' });
    }
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('icon navigation hides collapsed counts, expands over the map and preserves pinning and Explore focus', { timeout: 60000 }, async () => {
  const { page, errors } = await openPage();
  const shell = page.locator('.tapl-workbench'), sidebar = page.locator('.wb-sidebar');
  const pin = page.locator('[data-wb-focus="sidebar-pin"]');
  try {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    assert.equal(await shell.getAttribute('data-sidebar-expanded'), 'false');
    assert.equal((await sidebar.boundingBox()).width, 64);
    const railBox = await sidebar.boundingBox();
    const aligned = await sidebar.locator('.wb-nav-button > .wb-icon:first-child, .wb-fold-trigger > .wb-icon:first-child, .wb-workspace-heading > button .wb-icon, .wb-management-actions > button .wb-icon').evaluateAll(icons => icons.map(icon => {
      const b = icon.getBoundingClientRect(), hit = icon.closest('button').getBoundingClientRect();
      return { label: icon.closest('button').getAttribute('aria-label'), center: b.x+b.width/2, width: hit.width, height: hit.height };
    }));
    assert.ok(aligned.length >= 9);
    for (const icon of aligned) {
      assert.ok(Math.abs(icon.center-railBox.x-railBox.width/2) <= 1, `collapsed icon ${JSON.stringify(icon)} must center at ${railBox.x+railBox.width/2}`);
      assert.ok(icon.width >= 44 && icon.height >= 44, 'collapsed targets stay operable');
    }
    const navIcon = await page.locator('[data-wb-focus="nav:current"] > .wb-icon').boundingBox();
    assert.equal(await page.locator('.wb-management-actions > button').count(),1);
    assert.equal(await page.locator('.wb-management-actions > button').getAttribute('aria-label'),'디버그');
    for (const selector of ['[data-wb-focus="workspace-picker"] .wb-icon', '.wb-management-actions > button .wb-icon']) {
      const icon = await page.locator(selector).boundingBox();
      assert.ok(Math.abs(icon.x+icon.width/2-navIcon.x-navIcon.width/2)<1, selector);
      assert.equal(icon.width,17); assert.equal(icon.height,17);
    }
    assert.equal(await page.locator('.wb-topbar .wb-language-menu').count(), 0);
    const pinBox = await pin.boundingBox();
    const theme = await page.locator('[data-wb-focus="theme-toggle"]').boundingBox();
    assert.ok(theme.x + theme.width <= pinBox.x, 'pin is the rightmost control after theme');
    assert.equal(await page.locator('.wb-mm-top-controls button[aria-pressed]').count(),1,'active RUN exposes its follow toggle');
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
    await page.locator('.wb-explore-panel').waitFor({ state: 'detached' });
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

    await setLanguage(page, 'en');
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
    await page.locator('.wb-explore-panel').waitFor({ state: 'detached' });
    await page.setViewportSize({ width: 1280, height: 420 });
    const sidebar = page.locator('.wb-sidebar');
    assert.ok(await sidebar.evaluate(el => el.scrollHeight > el.clientHeight));
    await page.locator('.wb-discard-button').scrollIntoViewIfNeeded();
    assert.ok(await page.locator('.wb-discard-button').isVisible());
    await trigger.click();
    await page.locator('.wb-explore-panel').waitFor();
    await page.setViewportSize({ width: 600, height: 750 });
    await page.waitForFunction(() => document.querySelector('.wb-sidebar').inert);
    await page.locator('.wb-explore-panel').waitFor({ state: 'detached' });
    await page.locator('.wb-mobile-menu').click();
    await page.locator('[data-wb-focus="explore:PLAN"]').click();
    await page.locator('.wb-explore-panel').waitFor();
    await page.keyboard.press('Escape');
    await page.locator('.wb-explore-panel').waitFor({ state: 'detached' });
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
    await modal.waitFor({ state: 'detached' });
    assert.equal(await picker.evaluate(el => el === document.activeElement), true);
    assert.equal(await page.locator('.wb-run-tab[aria-selected="true"]').getAttribute('title'), current);
    await page.locator('[data-wb-focus="nav:tasks"]').click();
    await page.mouse.move(1400, 30);
    await page.waitForFunction(() => document.querySelector('.tapl-workbench').dataset.sidebarExpanded === 'false');
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
      await setLanguage(page, locale);
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

test('associative memories branch around the workspace with shared cues, exact sources and a persistent gesture camera', { timeout: 60000 }, async () => {
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
    assert.equal(await map.locator('[data-kind=workspace]').count(),1);
    assert.equal(await map.locator('g[data-relation]').count(),10);
    assert.equal(await map.locator('g[data-relation=workspace]').count(),2);
    assert.equal(await page.locator('.wb-memory-card').count(),0);
    const positions = await map.locator('[data-mindmap-node]').evaluateAll(nodes=>nodes.map(node=>{
      const matrix=new DOMMatrix(getComputedStyle(node).transform);
      return {kind:node.dataset.kind,x:matrix.e+node.offsetWidth/2,y:matrix.f+node.offsetHeight/2};
    }));
    const hub=positions.find(node=>node.kind==='workspace');
    assert.ok(Math.abs(hub.x)<1 && Math.abs(hub.y)<1,'workspace stays at the camera origin');
    const sources=positions.filter(node=>node.kind==='source');
    assert.ok(sources.some(node=>node.x>0) && sources.some(node=>node.x<0),'sparse sources spread on both sides of the hub');
    const cue = map.locator('[data-kind=cue] button').filter({hasText:'interface evidence'});
    await cue.focus(); await page.waitForTimeout(40);
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
      await setLanguage(page, locale);
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
    const sharedCue=map.locator('[data-kind=cue] button').filter({hasText:'interface evidence'});
    await sharedCue.focus(); await page.waitForTimeout(40); await sharedCue.click();
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

test('workspace memory hub distributes four source branches and keeps every rendered card separate', { timeout: 30000 }, async () => {
  const {page,errors}=await openPage();
  await page.route('**/api/message',async route=>{
    const request=route.request().postDataJSON();
    if(request.command!=='memories') return route.continue();
    const response=await route.fetch();const payload=await response.json();
    const originals=payload.view.memories;
    payload.view.memories=[...originals,...originals.map((memory,index)=>({...memory,id:`radial-preview-${index}`,source_available:false,source:{...memory.source,run_id:`radial-preview-run-${index}`,title:`Source branch ${index+3}`}}))];
    payload.view.total=payload.view.memories.length;
    return route.fulfill({response,json:payload});
  });
  try {
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.locator('[data-wb-focus="nav:memories"]').click();
    const map=page.locator('.wb-memory-mindmap');await map.waitFor();
    await page.mouse.move(1400,30);await page.waitForTimeout(650);
    const nodes=await map.locator('[data-mindmap-node]').evaluateAll(elements=>elements.map(element=>{
      const matrix=new DOMMatrix(getComputedStyle(element).transform),r=element.getBoundingClientRect();
      return {kind:element.dataset.kind,x:matrix.e+element.offsetWidth/2,y:matrix.f+element.offsetHeight/2,b:matrix.b,c:matrix.c,left:r.left,right:r.right,top:r.top,bottom:r.bottom};
    }));
    assert.equal(nodes.filter(node=>node.kind==='workspace').length,1);
    const sources=nodes.filter(node=>node.kind==='source');assert.equal(sources.length,4);
    assert.equal(new Set(sources.map(node=>Math.abs(node.x)>=Math.abs(node.y)?node.x>=0?'right':'left':node.y>=0?'bottom':'top')).size,4);
    for(let a=0;a<nodes.length;a++) {
      assert.equal(nodes[a].b,0);assert.equal(nodes[a].c,0,'card text never rotates');
      for(let b=a+1;b<nodes.length;b++) assert.ok(nodes[a].right<=nodes[b].left||nodes[b].right<=nodes[a].left||nodes[a].bottom<=nodes[b].top||nodes[b].bottom<=nodes[a].top,'rendered cards never overlap');
    }
    const hub=map.locator('[data-kind=workspace] button');
    const centerLabel=await hub.getAttribute('aria-label');assert.ok(centerLabel.includes('워크스페이스'));
    await hub.click();assert.equal(await map.count(),1,'the hub centers the view without opening a record');
    await shot(page,'memory-radial-four-way');
    assert.deepEqual(errors,[]);
  } finally {await page.close();}
});

test('native VS Code palettes update maps, chrome, controls and dialogs without overriding explicit themes', { timeout: 60000 }, async () => {
  const {page,errors}=await openPage();
  const palettes=[
    {mode:'vscode-dark',bg:'#101b2b',surface:'#1d2f43',fg:'#e8eff7',muted:'#a4b3c5',border:'#8d9bad',input:'#152337',inputFg:'#eaf2ff',button:'#27618c',buttonFg:'#ffffff',focus:'#f3bd66',link:'#7bbfff',code:'#0b1421',tip:'#283f58',tipFg:'#edf7ff',info:'#74bfff',passed:'#8ad8ac',error:'#f5a28a',warning:'#ffd075',skipped:'#ceafea',secondary:'#304359',secondaryFg:'#eef2f7'},
    {mode:'vscode-light',bg:'#f4f0e8',surface:'#fffcf6',fg:'#2d2434',muted:'#6d606e',border:'#8f798c',input:'#ede5df',inputFg:'#3b2a42',button:'#684386',buttonFg:'#ffffff',focus:'#ae4a2f',link:'#704398',code:'#e6dcd4',tip:'#f9e8d8',tipFg:'#3e2434',info:'#285ead',passed:'#247447',error:'#a63c36',warning:'#9b6b16',skipped:'#7d4892',secondary:'#e5d7e5',secondaryFg:'#4c3152'}
  ];
  // Distinct roles catch using an input/focus/panel color for ordinary separators.
  const borders=[
    {editor:'#454a56',surface:'#515963',sidebar:'#5b6470',group:'#697580',input:'#788493',widget:'#8c99a8',tooltip:'#9eabba'},
    {editor:'#c4c7cc',surface:'#b7bec6',sidebar:'#a8b2bd',group:'#929fae',input:'#7c8c9e',widget:'#687b91',tooltip:'#526b87'}
  ];
  const rgba=(selector,property)=>page.locator(selector).first().evaluate((element,property)=>{
    const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const context=canvas.getContext('2d');
    context.fillStyle=getComputedStyle(element)[property];context.fillRect(0,0,1,1);return [...context.getImageData(0,0,1,1).data];
  },property);
  const hex=value=>[...value.slice(1).match(/../g).map(part=>parseInt(part,16)),255];
  const native=async (p,border=borders[0])=>{
    await page.evaluate(p=>{
      delete document.documentElement.dataset.taplTheme;
      document.body.className=p.mode;
      const values={
        'sideBar-background':p.bg,'panel-background':p.bg,'editor-background':p.bg,'editorWidget-background':p.surface,
        'editor-foreground':p.fg,'descriptionForeground':p.muted,'panel-border':p.border,'input-border':p.borders.input,
        'editor-border':p.borders.editor,'surface-border':p.borders.surface,'sideBar-border':p.borders.sidebar,
        'editorGroup-border':p.borders.group,'editorWidget-border':p.borders.widget,'widget-border':'#ff00ff',
        'input-background':p.input,'input-foreground':p.inputFg,'button-background':p.button,'button-foreground':p.buttonFg,
        'button-hoverBackground':p.button,'button-secondaryBackground':p.secondary,'button-secondaryForeground':p.secondaryFg,
        'focusBorder':p.focus,'textLink-foreground':p.link,'textLink-activeForeground':p.link,'textCodeBlock-background':p.code,
        'editorHoverWidget-background':p.tip,'editorHoverWidget-foreground':p.tipFg,'editorHoverWidget-border':p.borders.tooltip,
        'editorInfo-foreground':p.info,'testing-iconPassed':p.passed,'errorForeground':p.error,'editorWarning-foreground':p.warning,
        'testing-iconSkipped':p.skipped,'list-hoverBackground':p.secondary,'contrastBorder':'#ffe066'
      };
      for(const [key,value] of Object.entries(values)) document.body.style.setProperty(`--vscode-${key}`,value);
    },{...p,borders:border});
    await page.waitForTimeout(350);
  };
  try {
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.locator('.wb-mm-follow').click(); // Compare unhighlighted native palette tokens.
    for(const [index,p] of palettes.entries()) {
      await page.locator('[data-wb-focus="nav:current"]').click();
      await page.locator('.wb-run-mindmap').waitFor();await page.mouse.move(1400,30);
      await native(p,borders[index]);
      assert.deepEqual(await rgba('.wb-run-mindmap','backgroundColor'),hex(p.bg));
      assert.deepEqual(await rgba('.wb-run-mindmap','color'),hex(p.fg));
      assert.deepEqual(await rgba('.wb-run-mindmap [data-kind=task] button','backgroundColor'),hex(p.surface));
      assert.deepEqual(await rgba('.wb-run-mindmap .wb-mm-state[data-status=progress]','color'),hex(p.info));
      assert.deepEqual(await rgba('.wb-run-mindmap .wb-mm-flow-tail','stroke'),hex(p.info));
      assert.deepEqual(await rgba('.wb-topbar','borderBottomColor'),hex(borders[index].editor));
      assert.deepEqual(await rgba('.wb-sidebar','borderRightColor'),hex(borders[index].editor));
      assert.deepEqual(await rgba('.wb-run-mindmap [data-kind=task] button','borderTopColor'),hex(borders[index].editor));
      await page.keyboard.press('Tab');await page.locator('.wb-run-mindmap').focus();
      assert.deepEqual(await rgba('.wb-run-mindmap','outlineColor'),hex(p.focus));
      await shot(page,`native-${index}-run`);
      await page.locator('[data-wb-focus="nav:tasks"]').click();await page.locator('.wb-tasks-table').waitFor();
      assert.deepEqual(await rgba('[data-wb-focus="filter:all"]','backgroundColor'),hex(p.button));
      assert.deepEqual(await rgba('[data-wb-focus="filter:all"]','color'),hex(p.buttonFg));
      assert.deepEqual(await rgba('.wb-pill-tabs','borderTopColor'),hex(borders[index].editor));
      assert.equal(new Set(await page.locator('.wb-tasks-table .wb-status-label').evaluateAll(nodes=>nodes.map(node=>getComputedStyle(node).color))).size,4);
      await page.locator('[data-wb-focus="nav:current"]').click();await page.locator('.wb-run-mindmap').waitFor();
      await page.mouse.move(1400,30);await page.waitForTimeout(650);
      const detailTask=page.locator('.wb-run-mindmap [data-kind=task] button').filter({hasText:'TASK-013'});
      await detailTask.focus();await page.waitForTimeout(60);await detailTask.click();
      await page.locator('.wb-record-page').waitFor();
      assert.deepEqual(await rgba('.wb-record-page h1','color'),hex(p.fg));
      await shot(page,`native-${index}-detail`);
      await page.locator('[data-wb-focus="nav:memories"]').click();await page.locator('.wb-memory-mindmap').waitFor();
      assert.deepEqual(await rgba('.wb-memory-mindmap','backgroundColor'),hex(p.bg));
      assert.deepEqual(await rgba('.wb-memory-mindmap','color'),hex(p.fg));
      assert.deepEqual(await rgba('.wb-memory-mindmap','borderTopColor'),hex(borders[index].editor));
      assert.deepEqual(await rgba('.wb-search-box .input','backgroundColor'),hex(p.input));
      assert.deepEqual(await rgba('.wb-search-box input','color'),hex(p.inputFg));
      await page.mouse.move(1400,30);await page.waitForTimeout(650);await shot(page,`native-${index}-memory`);
      await page.locator('[data-wb-focus="theme-toggle"]').hover();await page.getByRole('tooltip').waitFor();
      assert.deepEqual(await rgba('[role=tooltip]','backgroundColor'),hex(p.tip));
      assert.deepEqual(await rgba('[role=tooltip]','color'),hex(p.tipFg));
      assert.deepEqual(await rgba('[role=tooltip]','borderTopColor'),hex(borders[index].tooltip));
      await page.keyboard.press('Escape');
      await page.locator('[data-wb-focus="workspace-picker"]').click();await page.getByRole('dialog').waitFor();
      assert.deepEqual(await rgba('.wb-dialog','backgroundColor'),hex(p.surface));
      assert.deepEqual(await rgba('.wb-dialog','borderTopColor'),hex(borders[index].widget));
      assert.deepEqual(await rgba('.wb-dialog-input','borderTopColor'),hex(borders[index].input));
      await page.evaluate(()=>document.body.style.removeProperty('--vscode-editorWidget-border'));
      assert.deepEqual(await rgba('.wb-dialog','borderTopColor'),hex('#ff00ff'),'widget fallback stays independent of input borders');
      await page.evaluate(()=>document.body.style.removeProperty('--vscode-widget-border'));
      assert.deepEqual(await rgba('.wb-dialog','borderTopColor'),hex(borders[index].editor));
      await page.evaluate(border=>{
        document.body.style.setProperty('--vscode-editorWidget-border',border.widget);
        document.body.style.setProperty('--vscode-widget-border','#ff00ff');
      },borders[index]);
      assert.deepEqual(await rgba('.wb-dialog-input','backgroundColor'),hex(p.input));
      assert.deepEqual(await rgba('.wb-dialog .btn-primary','backgroundColor'),hex(p.button));
      assert.deepEqual(await rgba('.wb-dialog .btn-primary','color'),hex(p.buttonFg));
      await shot(page,`native-${index}-dialog`);
      await page.keyboard.press('Escape');await page.getByRole('dialog').waitFor({state:'detached'});
      await page.locator('[data-wb-focus="nav:settings"]').click();
      const settingInput=page.locator('[id="setting-search.max_results"]'); await settingInput.waitFor();
      assert.deepEqual(await rgba('[id="setting-search.max_results"]','backgroundColor'),hex(p.input));
      assert.deepEqual(await rgba('[id="setting-search.max_results"]','color'),hex(p.inputFg));
      assert.deepEqual(await rgba('[id="setting-search.max_results"]','borderTopColor'),hex(borders[index].input));
      assert.deepEqual(await rgba('.wb-settings-card','borderTopColor'),hex(borders[index].editor));
      assert.deepEqual(await rgba('.wb-settings-section-title','borderBottomColor'),hex(borders[index].editor));
      await settingInput.fill('0');
      assert.deepEqual(await rgba('.wb-settings-input-error','color'),hex(p.error));
      await shot(page,`native-${index}-settings`);
      await settingInput.fill('12');
      await page.locator('[data-wb-focus="nav:memories"]').click(); await page.locator('.wb-memory-mindmap').waitFor();
    }
    // Body-scoped host variables change live without remounting either map.
    await native(palettes[0]);assert.deepEqual(await rgba('.wb-memory-mindmap','backgroundColor'),hex(palettes[0].bg));
    for(const [remove,expected] of [
      ['editor-border',borders[0].surface],['surface-border',borders[0].sidebar],
      ['sideBar-border',palettes[0].border],['panel-border',borders[0].group]
    ]) {
      await page.evaluate(key=>document.body.style.removeProperty(`--vscode-${key}`),remove);
      assert.deepEqual(await rgba('.wb-topbar','borderBottomColor'),hex(expected),`fallback after ${remove}`);
      assert.deepEqual(await rgba('.wb-sidebar','borderRightColor'),hex(expected));
      assert.deepEqual(await rgba('.wb-memory-mindmap','borderTopColor'),hex(expected));
    }
    await page.evaluate(()=>document.body.style.removeProperty('--vscode-editorGroup-border'));
    assert.equal((await rgba('.wb-topbar','borderBottomColor'))[3],255,'missing theme borders retain a neutral opaque fallback');
    assert.notDeepEqual(await rgba('.wb-topbar','borderBottomColor'),hex(palettes[0].focus));
    await page.evaluate(()=>document.body.style.setProperty('--vscode-panel-border','#ffffff80'));
    assert.deepEqual(await rgba('.wb-topbar','borderBottomColor'),[255,255,255,128],'host alpha is preserved without extra mixing');
    await page.evaluate(()=>document.body.style.setProperty('--vscode-editor-border','transparent'));
    assert.equal((await rgba('.wb-topbar','borderBottomColor'))[3],0,'an intentionally transparent host border stays transparent');
    await native(palettes[0]);
    await page.evaluate(()=>document.body.className='vscode-high-contrast');
    assert.deepEqual(await rgba('.wb-topbar','borderBottomColor'),hex('#ffe066'));
    assert.deepEqual(await rgba('.wb-sidebar','borderRightColor'),hex('#ffe066'));
    assert.deepEqual(await rgba('.wb-memory-mindmap','borderTopColor'),hex('#ffe066'));
    await page.locator('[data-wb-focus="nav:current"]').click(); await page.locator('.wb-run-mindmap').waitFor();
    assert.deepEqual(await rgba('.wb-mm-edge-running .wb-mm-edge','stroke'),hex('#ffe066'));
    await page.locator('[data-wb-focus="nav:memories"]').click(); await page.locator('.wb-memory-mindmap').waitFor();
    await page.evaluate(()=>document.body.className='vscode-high-contrast-light');
    assert.deepEqual(await rgba('.wb-topbar','borderBottomColor'),hex('#ffe066'));
    assert.deepEqual(await rgba('.wb-memory-mindmap','borderTopColor'),hex('#ffe066'));
    await page.evaluate(()=>document.documentElement.dataset.taplTheme='light');
    await page.waitForTimeout(350);
    assert.deepEqual(await rgba('.wb-memory-mindmap','backgroundColor'),hex('#f7f8fa'));
    assert.deepEqual(await rgba('.wb-memory-mindmap','color'),hex('#222d3b'));
    assert.deepEqual(await rgba('.wb-topbar','borderBottomColor'),hex('#e9edf2'));
    assert.deepEqual(await rgba('.wb-memory-mindmap','borderTopColor'),hex('#dce2e9'));
    await page.evaluate(()=>document.body.style.setProperty('--vscode-sideBar-background','#ff00ff'));
    assert.deepEqual(await rgba('.wb-memory-mindmap','backgroundColor'),hex('#f7f8fa'),'manual light palette wins over native body values');
    await page.evaluate(()=>document.documentElement.dataset.taplTheme='dark');
    await page.waitForTimeout(350);
    assert.deepEqual(await rgba('.wb-memory-mindmap','backgroundColor'),hex('#151b24'));
    assert.deepEqual(await rgba('.wb-memory-mindmap','color'),hex('#e6edf5'));
    assert.deepEqual(await rgba('.wb-topbar','borderBottomColor'),hex('#293545'));
    assert.deepEqual(await rgba('.wb-memory-mindmap','borderTopColor'),hex('#364354'));
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
    await page.getByText('Legacy PLAN body repeats the structured fields.', { exact: false }).waitFor();
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
    await page.mouse.move(1400,100);await page.waitForTimeout(650);
    await shot(page, 'memories-ko-light');
    const findingMemory=page.locator('.wb-memory-mindmap [data-kind=memory]').filter({ hasText: 'original contrast finding' }).locator('button');
    await findingMemory.focus();await page.waitForTimeout(60);await findingMemory.click();
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
    await page.locator('[data-wb-focus="theme-toggle"]').focus();
    await page.getByRole('tooltip').waitFor();
    assert.equal(await page.getByRole('tooltip').innerText(), await page.locator('[data-wb-focus="theme-toggle"]').getAttribute('aria-label'));
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

test('RUN follows executing TASK and PLAN context with resistant gestures, refresh and source-safe preferences', { timeout: 60000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'ko-KR' });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  let overview;
  await page.route('**/api/message', async route => {
    const response = await route.fetch(), payload = await response.json();
    if (payload.view?.type === 'overview') {
      if (!overview) {
        payload.view.status.tasks.forEach((task, index, tasks) => { task.status = index === Math.floor(tasks.length / 2) ? 'In Progress' : 'Pending'; });
        overview = structuredClone(payload);
      } else if (payload.view.status.active_run?.id === overview.view.status.active_run.id) {
        payload.view.status = structuredClone(overview.view.status);
      }
    }
    await route.fulfill({ response, json: payload });
  });
  const map = page.locator('.wb-run-mindmap'), toggle = page.locator('[data-wb-focus="mindmap-follow"]');
  const camera = () => map.locator('.wb-mm-world').evaluate(el => { const m = new DOMMatrix(getComputedStyle(el).transform); return { x: m.e, y: m.f, z: m.a }; });
  const publish = async () => {
    await page.evaluate(payload => window.postMessage({ ...payload, type: 'view:update' }, '*'), overview);
    const expected = overview.view.status.tasks.filter(task => task.status === 'In Progress').map(task => `task:${task.id}`).sort();
    await page.waitForFunction(expected => {
      const actual = [...document.querySelectorAll('.wb-run-mindmap [data-kind=task] button[data-status="In Progress"]')]
        .map(node => node.dataset.wbFocus).sort();
      return JSON.stringify(actual) === JSON.stringify(expected);
    }, expected);
  };
  const centered = () => page.waitForFunction(() => {
    const map = document.querySelector('.wb-run-mindmap'), bounds = map.getBoundingClientRect();
    const tasks = [...map.querySelectorAll('[data-kind=task] button[data-status="In Progress"]')].map(el => el.closest('[data-kind]'));
    const targets = new Set(tasks);
    if (tasks.length) {
      const nodes = [...map.querySelectorAll('[data-mindmap-node]')];
      for (const task of tasks) {
        const edge = [...map.querySelectorAll('[data-from][data-to]')].find(edge => edge.dataset.to === task.dataset.mindmapNode);
        const parent = edge && nodes.find(node => node.dataset.mindmapNode === edge.dataset.from);
        if (parent?.dataset.kind === 'plan') targets.add(parent);
      }
    } else {
      for (const plan of map.querySelectorAll('[data-kind=plan] button[data-status="In Progress"]')) targets.add(plan.closest('[data-kind]'));
    }
    if (!targets.size) return false;
    const rectangles = [...targets].map(node => node.getBoundingClientRect());
    const left = Math.min(...rectangles.map(r => r.left)), right = Math.max(...rectangles.map(r => r.right));
    const top = Math.min(...rectangles.map(r => r.top)), bottom = Math.max(...rectangles.map(r => r.bottom));
    return Math.abs((left + right - bounds.left - bounds.right) / 2) < 1
      && Math.abs((top + bottom - bounds.top - bounds.bottom) / 2) < 1
      && left >= bounds.left && right <= bounds.right && top >= bounds.top && bottom <= bounds.bottom;
  });
  const enable = async () => { if (await toggle.getAttribute('aria-pressed') !== 'true') await toggle.click(); await centered(); };
  try {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(origin); await map.waitFor(); await centered();
    await shot(page, 'run-follow-task-plan');
    assert.ok((await camera()).z > 1, 'focused TASK and parent PLAN enlarge for readability');
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true');
    assert.equal(await toggle.getAttribute('aria-label'), '진행 중 TASK 추적');
    assert.equal(await toggle.getAttribute('title'), 'TASK 자동 추적 끄기');
    const first = map.locator('[data-kind=task] button[data-status="In Progress"]');
    await first.hover(); assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'hover keeps following');
    await first.click(); await page.locator('.wb-record-page').waitFor();
    await page.locator('.wb-back').click(); await map.waitFor(); await centered();
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'ordinary node navigation retains following');
    const box = await map.boundingBox(), x = box.x + box.width / 2, y = box.y + 40;
    const originCamera = await camera(), direction = originCamera.x > 0 ? -1 : 1;
    await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x + direction * 12, y + 8); await page.waitForTimeout(50);
    const resisted = await camera();
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true');
    assert.ok((resisted.x - originCamera.x) * direction > 4 && (resisted.x - originCamera.x) * direction < 8,
      'small drag visibly bends with soft resistance');
    await page.mouse.up(); await centered();
    await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x + direction * 219, y); await page.waitForTimeout(40);
    const held = await camera(); assert.equal(await toggle.getAttribute('aria-pressed'), 'true');
    await page.mouse.move(x + direction * 221, y); await page.waitForTimeout(40);
    const released = await camera(); assert.equal(await toggle.getAttribute('aria-pressed'), 'false');
    assert.ok(Math.abs(released.x - held.x) < 3, 'crossing the magnet threshold has no jump');
    await page.mouse.move(x + direction * 251, y); await page.waitForTimeout(40);
    assert.ok(((await camera()).x - released.x) * direction > 20, 'same pointer gesture continues free pan');
    await page.mouse.up();
    await page.getByRole('tab', { name: /Second active RUN/ }).click();
    await map.waitFor();
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'another RUN starts following');
    await page.getByRole('tab', { name: /Viewer redesign/ }).click(); await map.waitFor();
    assert.equal(await toggle.getAttribute('aria-pressed'), 'false', 'return retains the selected RUN preference');
    await enable();
    await map.evaluate(el => {
      const rect = el.getBoundingClientRect(), init = { bubbles: true, pointerId: 71, pointerType: 'touch', button: 0, clientX: rect.x + rect.width / 2, clientY: rect.y + 40 };
      el.dispatchEvent(new PointerEvent('pointerdown', init));
      window.dispatchEvent(new PointerEvent('pointermove', { ...init, clientX: init.clientX + 14 }));
      window.dispatchEvent(new PointerEvent('pointerup', { ...init, clientX: init.clientX + 14 }));
    });
    await centered(); assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'single touch drag has the same resistance');
    for (const action of [
      () => map.locator('.wb-mm-camera-controls button').last().click(),
      async () => { await map.focus(); await page.keyboard.press('ArrowRight'); },
      () => map.locator('.wb-mm-camera-controls button').nth(1).click()
    ]) {
      await action(); assert.equal(await toggle.getAttribute('aria-pressed'), 'false', 'manual camera action releases tracking');
      await map.evaluate(el => el.dispatchEvent(new Event('gestureend', { bubbles: true, cancelable: true })));
      await enable();
    }
    const wheel = (deltaX, deltaY, extra = {}) => map.evaluate((el, input) => {
      const rect = el.getBoundingClientRect();
      el.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, clientX: rect.x + rect.width / 2,
        clientY: rect.y + 40, ...input }));
      return new Promise(resolve => requestAnimationFrame(() => {
        const matrix = new DOMMatrix(getComputedStyle(el.querySelector('.wb-mm-world')).transform);
        resolve({ x: matrix.e, y: matrix.f, z: matrix.a });
      }));
    }, { deltaX, deltaY, ...extra });
    await wheel(0, 0); assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'zero wheel input is inert');
    for (let burst = 0; burst < 3; burst++) {
      const bent = await wheel(0, 70);
      assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'small trackpad pan resists');
      const travel = originCamera.y - bent.y;
      assert.ok(travel > 8 && travel < 20, `small trackpad movement bends softly: ${JSON.stringify({ originCamera, bent })}`);
      await centered();
    }
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'separated gestures never accumulate intent');
    const wheelStroke = await map.evaluate(async el => {
      const read = () => new DOMMatrix(getComputedStyle(el.querySelector('.wb-mm-world')).transform).e;
      const following = () => el.querySelector('.wb-mm-follow').getAttribute('aria-pressed') === 'true';
      let held = read(), steps = 0;
      while (following() && steps < 40) {
        held = read(); steps++;
        el.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaX: 20 }));
        await new Promise(resolve => requestAnimationFrame(resolve));
      }
      return { held, released: read(), steps };
    });
    assert.ok(wheelStroke.steps > 10 && wheelStroke.steps < 40, 'one moderate continuous stroke reaches the corrected release distance');
    assert.ok(Math.abs(wheelStroke.held-originCamera.x) > 30, 'view visibly bends before release');
    assert.equal(await toggle.getAttribute('aria-pressed'), 'false', 'continuous net wheel motion releases');
    assert.ok(Math.abs(wheelStroke.released-wheelStroke.held) < 8, `wheel release is continuous: ${JSON.stringify(wheelStroke)}`);
    await enable();
    const softPinch = await wheel(0, -20, { ctrlKey: true });
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'small ctrl-wheel pinch stays magnetic');
    assert.ok(softPinch.z > originCamera.z * 1.05 && softPinch.z < originCamera.z * 1.15,
      `small pinch bends softly: ${JSON.stringify({ originCamera, softPinch })}`);
    await centered();
    await wheel(0, -60, { ctrlKey: true });
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'pinch has a long elastic scale range');
    await wheel(0, -5, { ctrlKey: true });
    assert.equal(await toggle.getAttribute('aria-pressed'), 'false', 'sustained ctrl-wheel pinch releases');
    await enable();
    const native = (type, scale) => map.evaluate((el, { type, scale }) => {
      const event = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperty(event, 'scale', { value: scale }); el.dispatchEvent(event);
    }, { type, scale });
    await native('gesturestart', 1);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'native pinch start alone keeps follow');
    await native('gesturechange', 1.12); await page.waitForTimeout(25);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'small native pinch resists');
    await native('gesturechange', NaN);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'invalid native scale is ignored');
    await native('gesturecancel', 1.12); await centered();
    await native('gesturestart', 1); await native('gesturechange', 1e100); await page.waitForTimeout(25);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'false');
    assert.ok((await camera()).z <= 2.8, 'huge pinch respects the zoom ceiling at release');
    await native('gestureend', 1e100); await enable();
    await native('gesturestart', 1); await native('gesturechange', 1e-100); await page.waitForTimeout(25);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'false');
    assert.ok((await camera()).z >= .08, 'huge contraction respects the manual zoom floor');
    await native('gestureend', 1e-100); await enable();
    const touch = (type, id, offset) => map.evaluate((el, { type, id, offset }) => {
      const rect = el.getBoundingClientRect();
      const event = new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: id, pointerType: 'touch',
        button: 0, clientX: rect.x + rect.width / 2 + offset, clientY: rect.y + 40 });
      (type === 'pointerdown' ? el : window).dispatchEvent(event);
    }, { type, id, offset });
    await touch('pointerdown', 81, -50); await touch('pointerdown', 82, 50);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'second finger alone keeps follow');
    await touch('pointermove', 82, 60); await page.waitForTimeout(25);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'small touch pinch resists');
    await touch('pointercancel', 82, 60); await touch('pointermove', 81, -40);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'cancel rebases remaining finger without release');
    await touch('pointerup', 81, -40); await centered();
    await touch('pointerdown', 81, -50); await touch('pointerdown', 82, 50); await touch('pointermove', 82, 130);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'false', 'deliberate touch pinch releases');
    await touch('pointerup', 82, 130); await touch('pointerup', 81, -50); await enable();
    // Snapshot replacement and resize must cancel pending wheel springback timers.
    await page.waitForTimeout(150); await wheel(0, 50);
    overview.view.status.tasks.forEach((task, index, tasks) => { task.status = index === tasks.length - 1 ? 'In Progress' : 'Pending'; });
    await publish(); await centered();
    const moved = await camera(); assert.ok(Math.abs(moved.y - originCamera.y) > 100, 'snapshot follows the new executing TASK');
    overview.view.status.tasks[0].status = 'In Progress'; await publish(); await centered();
    const multiple = await camera(); assert.ok(multiple.z < moved.z, 'concurrent TASKs fit together');
    await page.setViewportSize({ width: 390, height: 360 }); await centered();
    await shot(page, 'run-follow-task-plan-short');
    assert.ok((await camera()).z <= multiple.z, 'resize recomputes the executing boundaries');
    await page.setViewportSize({ width: 1440, height: 1000 }); await centered();
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    overview.view.status.tasks[0].status = 'Pending'; await publish(); await centered();
    overview.view.status.tasks.forEach(task => { task.status = 'Completed'; });
    overview.view.status.plans.forEach((plan, index) => { plan.status = index === 0 ? 'In Progress' : 'Finalized'; });
    await publish(); await centered();
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'PLAN-only execution remains framed');
    overview.view.status.plans.forEach(plan => { plan.status = 'Finalized'; }); await publish();
    await page.waitForFunction(() => { const m = new DOMMatrix(getComputedStyle(document.querySelector('.wb-mm-world')).transform); return Math.abs(m.e) < .1 && Math.abs(m.f) < .1; });
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'no executing TASK returns to RUN view without disabling');
    await toggle.click();
    const status = overview.view.status;
    const originalSnapshot = { run: { ...status.active_run, source_db: status.active_run.source_db ?? status.source_db }, plans: status.plans, tasks: status.tasks, findings: [], task_counts: status.task_counts, active_batches: [], active_executions: [], readonly: false };
    const peerSnapshot = structuredClone(originalSnapshot); peerSnapshot.run.source_db += '.peer';
    for (const item of [...peerSnapshot.tasks, ...peerSnapshot.plans]) item.source_db = peerSnapshot.run.source_db;
    const postSnapshot = snapshot => page.evaluate(snapshot => window.postMessage({ type: 'view:update', view: { type: 'run', snapshot } }, '*'), snapshot);
    await postSnapshot(peerSnapshot);
    await page.waitForFunction(source => JSON.parse(document.querySelector('.wb-run-mindmap').dataset.runKey)[0] === source, peerSnapshot.run.source_db);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'same RUN ID in another DB has a separate preference');
    await postSnapshot(originalSnapshot);
    await page.waitForFunction(source => JSON.parse(document.querySelector('.wb-run-mindmap').dataset.runKey)[0] === source, originalSnapshot.run.source_db);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'false', 'source preference restores independently');
    originalSnapshot.run.status = 'completed'; await postSnapshot(originalSnapshot);
    await toggle.waitFor({ state: 'detached' });
    assert.equal(await map.getAttribute('data-following'), null, 'ended RUN no longer tracks');
    await page.reload(); await map.waitFor();
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true', 'reload resets to following');
    await page.locator('[data-wb-focus="nav:memories"]').click(); await page.locator('.wb-memory-mindmap').waitFor();
    assert.equal(await toggle.count(), 0); assert.equal(await page.locator('.wb-memory-mindmap').getAttribute('data-following'), null);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('trackpad acceleration stays attached, direct input has no extra easing, and momentum cannot stretch or replay the return', { timeout: 30000 }, async () => {
  const { page, errors } = await openPage();
  try {
    await page.mouse.move(1400, 30);
    const traces = await page.locator('.wb-run-mindmap').evaluate(async el => {
      const frame = () => new Promise(resolve => requestAnimationFrame(resolve));
      const frames = async count => { for (let i = 0; i < count; i++) await frame(); };
      const read = () => { const m = new DOMMatrix(getComputedStyle(el.querySelector('.wb-mm-world')).transform); return m.e; };
      const toggle = el.querySelector('.wb-mm-follow');
      const following = () => toggle.getAttribute('aria-pressed') === 'true';
      const wheel = (deltaX, momentum) => {
        const r = el.getBoundingClientRect();
        const event = new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaX, clientX: r.x+r.width/2, clientY: r.y+40 });
        Object.defineProperty(event, 'momentum', { value: momentum });
        el.dispatchEvent(event);
      };
      const reset = async () => { if (following()) toggle.click(); toggle.click(); await frames(35); };
      const result = [];
      for (const native of [true, false]) {
        await reset(); const origin = read();
        const direct = native ? false : undefined, momentum = native ? true : undefined;
        wheel(120, direct); await frame(); const immediate = read();
        await frames(4); const later = read();
        await reset();
        for (const delta of [12, 40, 100]) { wheel(delta, direct); await frame(); }
        const peak = Math.abs(read()-origin), attached = following(), tail = [];
        for (const delta of [60, 40, 25, 16, 10, 6, 4, 2, 1, .5, .25, .1, .05]) {
          wheel(delta, momentum); await frame(); tail.push(Math.abs(read()-origin));
        }
        const before = read(); wheel(-120, direct); await frame(); const after = read();
        result.push({ native, immediate: immediate-origin, later: later-origin, peak, attached, tail, regrab: after-before, following: following() });
      }
      return result;
    });
    for (const trace of traces) {
      const detail = JSON.stringify(trace);
      assert.ok(Math.abs(trace.immediate) > 2, `direct input moves on the next frame: ${detail}`);
      assert.ok(Math.abs(trace.later-trace.immediate) < .2, `no second easing stretches direct input: ${detail}`);
      assert.ok(trace.peak > 12 && trace.peak < 55, `accelerated spike is compressed: ${detail}`);
      assert.equal(trace.attached, true, detail);
      assert.ok(trace.tail.at(-1) < trace.peak*.4, `return progresses while momentum is still arriving: ${detail}`);
      assert.ok(trace.regrab > 2 && trace.regrab < 18, `new input starts at the visible return position across frame cadences: ${detail}`);
      assert.equal(trace.following, true, `momentum cannot release following: ${detail}`);
    }
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('same RUN refresh preserves sustained pointer, trackpad and native pinch gestures', { timeout: 30000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'en-US' });
  let overview;
  await page.route('**/api/message', async route => {
    const response = await route.fetch(), payload = await response.json();
    if (payload.view?.type === 'overview') overview = structuredClone(payload);
    await route.fulfill({ response, json: payload });
  });
  try {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(origin); await page.locator('.wb-run-mindmap').waitFor();
    const trace = await page.locator('.wb-run-mindmap').evaluate(async (el, payload) => {
      const frame = () => new Promise(resolve => requestAnimationFrame(resolve));
      const frames = async count => { for (let index = 0; index < count; index++) await frame(); };
      const read = () => { const m = new DOMMatrix(getComputedStyle(el.querySelector('.wb-mm-world')).transform); return { x: m.e, y: m.f, z: m.a }; };
      const toggle = () => el.querySelector('[data-wb-focus="mindmap-follow"]');
      const following = () => toggle().getAttribute('aria-pressed') === 'true';
      const enable = async () => { if (!following()) toggle().click(); await frames(3); };
      const refresh = async () => {
        payload.view.status.tasks[0].title += ' updated';
        window.postMessage({ ...payload, type: 'view:update' }, '*'); await frames(3);
      };
      const rect = el.getBoundingClientRect(), x = rect.x + rect.width / 2, y = rect.y + 100;
      const pointer = (type, clientX) => (type === 'pointerdown' ? el : window).dispatchEvent(new PointerEvent(type,
        { bubbles: true, cancelable: true, pointerId: 111, pointerType: 'touch', button: 0, clientX, clientY: y }));
      const wheel = deltaX => el.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaX, clientX: x, clientY: y }));
      const native = (type, scale) => { const event = new Event(type, { bubbles: true, cancelable: true }); Object.defineProperty(event, 'scale', { value: scale }); el.dispatchEvent(event); };
      await frames(3);
      pointer('pointerdown', x); pointer('pointermove', x + 120); await frame(); const held = read();
      await refresh(); const afterRefresh = read();
      pointer('pointermove', x + 180); await frame(); const continued = read();
      pointer('pointermove', x + 250); await frame(); const pointerReleased = !following();
      pointer('pointerup', x + 250); await enable();
      wheel(700); await frame(); const wheelHeld = read();
      await refresh(); const wheelAfterRefresh = read();
      wheel(600); await frame();
      for (let i = 0; i < 80 && following(); i++) { wheel(100); await frame(); }
      const wheelReleased = !following();
      await enable();
      native('gesturestart', 1); native('gesturechange', 1.2); await frame();
      await refresh(); native('gesturechange', 1.7); await frame(); const nativeReleased = !following();
      native('gestureend', 1.7);
      await enable(); await frames(10);
      wheel(50); window.dispatchEvent(new Event('blur'));
      payload.view.status.tasks.forEach((task, index, tasks) => { task.status = index === tasks.length - 1 ? 'In Progress' : 'Pending'; });
      await refresh(); await frames(3);
      const nodes = [...el.querySelectorAll('[data-mindmap-node]')], active = nodes.filter(node => node.dataset.kind === 'task'
        && node.querySelector('button[data-status="In Progress"]'));
      const targets = new Set(active);
      for (const task of active) {
        const edge = [...el.querySelectorAll('[data-from][data-to]')].find(edge => edge.dataset.to === task.dataset.mindmapNode);
        const parent = edge && nodes.find(node => node.dataset.mindmapNode === edge.dataset.from);
        if (parent?.dataset.kind === 'plan') targets.add(parent);
      }
      const rectangles = [...targets].map(node => node.getBoundingClientRect()), viewport = el.getBoundingClientRect();
      const blurCenterError = Math.abs((Math.min(...rectangles.map(r => r.left)) + Math.max(...rectangles.map(r => r.right)) - viewport.left - viewport.right) / 2)
        + Math.abs((Math.min(...rectangles.map(r => r.top)) + Math.max(...rectangles.map(r => r.bottom)) - viewport.top - viewport.bottom) / 2);
      return { held, afterRefresh, continued, pointerReleased, wheelHeld, wheelAfterRefresh, wheelReleased, nativeReleased, blurCenterError };
    }, overview);
    const detail = JSON.stringify(trace);
    assert.ok(Math.abs(trace.afterRefresh.x - trace.held.x) < .05, `refresh retains the held position: ${detail}`);
    assert.ok(trace.continued.x - trace.held.x > 10, `same pointer continues after refresh: ${detail}`);
    assert.equal(trace.pointerReleased, true, detail);
    assert.ok(Math.abs(trace.wheelAfterRefresh.x - trace.wheelHeld.x) < .05, `refresh retains wheel travel: ${detail}`);
    assert.equal(trace.wheelReleased, true, `wheel distance accumulates across refresh: ${detail}`);
    assert.equal(trace.nativeReleased, true, `native pinch keeps its gesture baseline: ${detail}`);
    assert.ok(trace.blurCenterError < 1, `blur clears input activity and refresh follows the latest target: ${detail}`);
  } finally { await page.close(); }
});

test('follow return settles smoothly and regrabbing or lifting one pinch finger never snaps', { timeout: 30000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'en-US' });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  try {
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.goto(origin); await page.locator('.wb-run-mindmap').waitFor();
    const trace = await page.locator('.wb-run-mindmap').evaluate(async el => {
      const frame = () => new Promise(resolve => requestAnimationFrame(resolve));
      const frames = async count => { for (let index = 0; index < count; index++) await frame(); };
      const read = () => { const m = new DOMMatrix(getComputedStyle(el.querySelector('.wb-mm-world')).transform); return { x: m.e, y: m.f, z: m.a }; };
      const steady = async () => {
        let previous = read(), stable = 0;
        for (let index = 0; index < 150; index++) {
          await frame(); const next = read();
          stable = Math.abs(next.x - previous.x) < .001 && Math.abs(next.y - previous.y) < .001 && Math.abs(next.z - previous.z) < .00001 ? stable + 1 : 0;
          if (stable >= 3) return next;
          previous = next;
        }
        throw new Error('Return camera never settled');
      };
      const rect = el.getBoundingClientRect(), x = rect.x + rect.width / 2, y = rect.y + 100;
      const pointer = (type, id, clientX) => {
        const event = new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: id, pointerType: 'touch', button: 0, clientX, clientY: y });
        (type === 'pointerdown' ? el : window).dispatchEvent(event);
      };
      const wheel = deltaX => el.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaX, clientX: x, clientY: y }));
      const baseline = await steady();
      pointer('pointerdown', 91, x); pointer('pointermove', 91, x + 160); await frames(2);
      const held = read(); pointer('pointerup', 91, x + 160); await frame(); const first = read();
      await frames(5); const interrupted = read();
      pointer('pointerdown', 92, x); await frame(); const restart = read();
      pointer('pointermove', 92, x + 15); await frame(); const continued = read();
      pointer('pointerup', 92, x + 15); const settled = await steady();
      wheel(600); await frame(); wheel(600);
      let wheelReturning = read();
      for (let index = 0; index < 120; index++) {
        await frame(); const next = read();
        const returning = Math.abs(next.x - baseline.x) < Math.abs(wheelReturning.x - baseline.x) - .05;
        wheelReturning = next;
        if (returning && Math.abs(next.x - baseline.x) > 10) break;
        if (index === 119) throw new Error('Wheel did not begin returning');
      }
      wheel(15); await frame(); const wheelRestart = read();
      await new Promise(resolve => setTimeout(resolve, 220)); // The direct packet has no physical end event; wait for idle return.
      const wheelSettled = await steady();
      pointer('pointerdown', 93, x - 50); pointer('pointerdown', 94, x + 50);
      pointer('pointermove', 94, x + 60); await frames(2); const pinchHeld = read();
      pointer('pointerup', 94, x + 60); await frame(); const oneFinger = read();
      pointer('pointerup', 93, x - 50); await frame(); const pinchFirst = read();
      const pinchSettled = await steady();
      return { baseline, held, first, interrupted, restart, continued, settled, wheelReturning, wheelRestart, wheelSettled, pinchHeld, oneFinger, pinchFirst, pinchSettled };
    });
    const detail = JSON.stringify(trace), distance = trace.held.x - trace.baseline.x;
    assert.ok(distance > 40 && distance < 100, detail);
    assert.ok(Math.abs(trace.first.x - trace.held.x) < distance * .12, `return starts gently: ${detail}`);
    assert.ok(Math.abs(trace.restart.x - trace.interrupted.x) < .05, `regrab stays at the visible position: ${detail}`);
    assert.ok(trace.continued.x - trace.restart.x > 3, `regrab continues bending: ${detail}`);
    assert.ok(Math.abs(trace.settled.x - trace.baseline.x) < .1, detail);
    assert.ok(Math.abs(trace.wheelReturning.x - trace.baseline.x) > 10, detail);
    assert.ok(Math.abs(trace.wheelRestart.x - trace.wheelReturning.x) < 5, `wheel reentry never resets to the follow center: ${detail}`);
    assert.ok(Math.abs(trace.wheelSettled.x - trace.baseline.x) < .1, detail);
    assert.ok(Math.abs(trace.oneFinger.x - trace.pinchHeld.x) < .05 && Math.abs(trace.oneFinger.z - trace.pinchHeld.z) < .0001, `remaining finger keeps the view: ${detail}`);
    assert.ok(Math.abs(trace.pinchFirst.z - trace.pinchHeld.z) < Math.abs(trace.pinchHeld.z - trace.baseline.z) * .12, `pinch return starts gently: ${detail}`);
    assert.ok(Math.abs(trace.pinchSettled.z - trace.baseline.z) < .0001, detail);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

async function observeWorkbenchMotion(page) {
  await page.addInitScript(() => {
    const animate = Element.prototype.animate;
    window.__wbMotion = []; window.__wbHeldExits = []; window.__wbHoldExits = false;
    Element.prototype.animate = function(frames, options) {
      const animation = animate.call(this, frames, options);
      window.__wbMotion.push({ id: this.id, className: this.className, frames });
      if (window.__wbHoldExits && frames.at(-1)?.opacity === 0) {
        animation.pause(); window.__wbHeldExits.push(animation);
      }
      return animation;
    };
  });
}

test('page motion waits for route content, ignores polling/filter/locale updates, and retains settings DOM', { timeout: 45000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'ko-KR' });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await observeWorkbenchMotion(page);
  let overview, releaseRecords;
  const recordsGate = new Promise(resolve => { releaseRecords = resolve; });
  await page.route('**/api/message', async route => {
    const command = route.request().postDataJSON().command;
    if (command === 'records') await recordsGate;
    const response = await route.fetch(), payload = await response.json();
    if (payload.view?.type === 'overview') overview = structuredClone(payload);
    await route.fulfill({ response, json: payload });
  });
  const count = () => page.evaluate(() => window.__wbMotion.filter(entry => entry.id === 'wb-page-content').length);
  try {
    await page.goto(origin); await page.locator('.wb-run-mindmap').waitFor();
    await page.locator('#wb-page-content').evaluate(el => { el.__retained = true; });
    const initial = await count();
    await page.locator('[data-wb-focus="nav:tasks"]').click(); await page.locator('.wb-tasks-table').waitFor();
    assert.equal(await count(), initial + 1);
    await page.locator('[data-wb-focus="task-query"]').fill('task 1');
    await page.locator('[data-wb-focus="filter:In Progress"]').click();
    const afterFilter = await count();
    await page.evaluate(payload => window.postMessage({ ...payload, locale: 'en', type: 'view:update' }, '*'), overview);
    await page.waitForFunction(() => document.documentElement.lang === 'en');
    assert.equal(await count(), afterFilter, 'background hydration and locale changes do not replay page entry');
    await page.locator('[data-wb-focus="nav:records"]').click();
    await page.waitForTimeout(220);
    assert.equal(await count(), afterFilter, 'pending placeholder does not consume destination entry');
    releaseRecords(); await page.locator('.wb-search-group').first().waitFor();
    assert.equal(await count(), afterFilter + 1, 'actual response enters once');
    await page.mouse.move(1400, 30);
    await page.waitForFunction(() => document.querySelector('.tapl-workbench')?.dataset.sidebarExpanded === 'false');
    await page.locator('.wb-search-group-header').first().click();
    await page.locator('.wb-search-result').first().click(); await page.locator('.wb-record-page').waitFor();
    assert.equal(await count(), afterFilter + 2, 'a record detail has its own route entry');
    await page.locator('[data-wb-focus="nav:settings"]').click();
    const input = page.locator('[id="setting-search.max_results"]'); await input.waitFor();
    await input.fill('37'); await input.evaluate(el => { el.__retainedDraft = true; });
    await page.locator('[data-wb-focus="nav:tasks"]').click();
    await page.locator('[data-wb-focus="task-query"]').waitFor();
    await page.locator('[data-wb-focus="nav:settings"]').click();
    assert.equal(await input.inputValue(), '37');
    assert.equal(await input.evaluate(el => el.__retainedDraft), true);
    assert.equal(await page.locator('#wb-page-content').evaluate(el => el.__retained), true);
    assert.deepEqual(errors, []);
  } finally { releaseRecords(); await page.close(); }
});

test('surface exits are inert, reopen cancels cleanup, and reduced motion clears modal and mobile scrim immediately', { timeout: 45000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'ko-KR' });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await observeWorkbenchMotion(page);
  try {
    await page.goto(origin); await page.locator('.wb-run-mindmap').waitFor();
    await page.evaluate(() => { window.__wbHoldExits = true; });
    const trigger = page.locator('[data-wb-focus="explore:TASK"]'), panel = page.locator('.wb-explore-panel');
    await trigger.focus(); await page.keyboard.press('ArrowRight'); await panel.waitFor();
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.querySelector('.wb-explore-panel')?.inert);
    assert.equal(await trigger.getAttribute('aria-expanded'), 'false');
    assert.equal(await trigger.evaluate(el => el === document.activeElement), true);
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(() => document.querySelector('.wb-explore-panel')?.inert === false);
    await page.evaluate(() => window.__wbHeldExits.forEach(animation => animation.dispatchEvent(new Event('finish'))));
    assert.equal(await panel.count(), 1, 'stale exit cannot remove the reopened panel');
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.querySelector('.wb-explore-panel')?.inert);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await panel.waitFor({ state: 'detached' });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    const picker = page.locator('[data-wb-focus="workspace-picker"]'), modal = page.locator('.wb-workspace-dialog');
    await picker.click(); await modal.waitFor();
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.querySelector('.wb-workspace-dialog')?.inert);
    assert.equal(await modal.evaluate(el => el.open), true, 'native top layer lasts through exit');
    await page.emulateMedia({ reducedMotion: 'reduce' }); await modal.waitFor({ state: 'detached' });
    assert.equal(await picker.evaluate(el => el === document.activeElement), true);
    await picker.click(); await modal.waitFor(); await page.keyboard.press('Escape');
    await modal.waitFor({ state: 'detached' });
    await page.setViewportSize({ width: 390, height: 740 });
    await page.locator('.wb-mobile-menu').click(); await page.locator('.wb-sidebar-scrim').waitFor();
    await page.keyboard.press('Escape'); await page.locator('.wb-sidebar-scrim').waitFor({ state: 'detached' });
    assert.equal(await page.locator('.wb-sidebar').evaluate(el => el.inert), true);
    assert.equal(await page.locator('.wb-page-scroll').evaluate(el => el.inert), false);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

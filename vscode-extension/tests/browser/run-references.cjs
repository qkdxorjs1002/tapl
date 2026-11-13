const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { spawn, spawnSync } = require('node:child_process');
const { mkdtempSync, realpathSync, rmSync, mkdirSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { chromium } = require('@playwright/test');

const root = path.resolve(__dirname, '../../..');
const python = process.env.TAPL_PYTHON || path.join(root, 'tapl/.venv/bin/python');
const fixture = path.join(root, 'vscode-extension/tests/fixtures/workbench.py');
const workspace = realpathSync(mkdtempSync(path.join(tmpdir(), 'tapl-run-refs-')));
let browser, server, origin, evidence;

function runPython(code) {
  const result = spawnSync(python, ['-c', code, workspace], {
    cwd: root, encoding: 'utf8', env: { ...process.env, PYTHONPATH: path.join(root, 'tapl'), PYTHONDONTWRITEBYTECODE: '1' }
  });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}
const context = `import json,sys,sqlite3
from pathlib import Path
from taplctl import application
workspace=Path(sys.argv[1])
app=application.WorkflowApplication(workspace)
app._db_path=workspace/'.tapl/tapl.db'
`;

before(async () => {
  const seeded = spawnSync(python, [fixture, '--workspace', workspace, '--seed-only'], { cwd: root, encoding: 'utf8' });
  assert.equal(seeded.status, 0, seeded.stderr);
  evidence = runPython(context + `memories=app.recall()['memories']
item_memory=next(m for m in memories if m['source']['item_id'] is not None)
run_memory=next(m for m in memories if m['source']['item_id'] is None)
app.get_item(item_memory['source']['item_id'],source_db=item_memory['source_db'])
with sqlite3.connect(app._db_path) as conn:
 events=conn.execute("SELECT count(*) FROM events WHERE event_type='run_references_updated'").fetchone()[0]
print(json.dumps({'item_memory':item_memory,'run_memory':run_memory,'run':app.get_status()['active_run'],'events':events}))`);
  server = spawn(python, [fixture, '--workspace', workspace, '--port', '0'], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  origin = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Viewer startup timed out')), 15000);
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Viewer exited: ${code}`)); });
    server.stdout.on('data', chunk => {
      const match = String(chunk).match(/tapl viewer: (http:\/\/\S+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
    server.stderr.on('data', chunk => process.stderr.write(chunk));
  });
  browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : { channel: 'chrome' });
});
after(async () => {
  await browser?.close();
  if (server && server.exitCode === null) {
    const done = new Promise(resolve => server.once('exit', resolve)); server.kill(); await done;
  }
  rmSync(workspace, { recursive: true, force: true });
});
const card = (page, target) => page.locator('.wb-run-mindmap [data-mindmap-node]').filter({
  has: page.locator('.wb-mm-reference-origin', { hasText: target })
});
async function back(page, runKey) {
  await page.locator('.wb-back-layer .wb-back:visible, .wb-mm-top-controls .wb-back:visible').click();
  await page.waitForFunction(key => document.querySelector('.wb-run-mindmap')?.dataset.runKey === key, runKey);
}
async function jump(page, kind) {
  await page.locator(`.wb-mm-reference-jump[data-reference-kind=${kind}]`).click();
  assert.equal(await page.locator('[data-wb-focus=mindmap-follow]').getAttribute('aria-pressed'), 'false');
}

async function assertSideBands(page, selector) {
  const result = await page.locator(selector).evaluate(host => {
    const nodes = new Map([...host.querySelectorAll('[data-mindmap-node]')].map(node => [node.dataset.mindmapNode, node]));
    const failures = [], edges = [...host.querySelectorAll('[data-from][data-to]')];
    for (const edge of edges) {
      const values = edge.querySelector('path').getAttribute('d').match(/[-+]?(?:\d*\.?\d+)(?:e[-+]?\d+)?/gi).map(Number);
      for (const [key, point] of [[edge.dataset.from, values.slice(0, 2)], [edge.dataset.to, values.slice(-2)]]) {
        const node = nodes.get(key), matrix = new DOMMatrix(node.style.transform);
        const width = Number.parseFloat(node.style.width), height = Number.parseFloat(node.style.height);
        const dx = Math.abs(point[0] - matrix.e - width / 2), dy = Math.abs(point[1] - matrix.f - height / 2);
        const onHorizontalSide = Math.abs(dy - height / 2) < .05 && dx <= width * .175 + .05;
        const onVerticalSide = Math.abs(dx - width / 2) < .05 && dy <= height * .175 + .05;
        if (!onHorizontalSide && !onVerticalSide) {
          failures.push({ kind: node.dataset.kind, point, dx, dy, width, height });
        }
      }
    }
    return { count: edges.length, failures };
  });
  assert.ok(result.count > 0);
  assert.deepEqual(result.failures, [], 'every SVG endpoint stays in the central 35% of its side');
}

test('real agent reads show exact original-only links; Viewer navigation leaves trace and owning RUN intact', async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'ko-KR', reducedMotion: 'reduce' });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(origin); await page.waitForLoadState('networkidle');
    const map = page.locator('.wb-run-mindmap'); await map.waitFor();
    await assertSideBands(page, '.wb-run-mindmap');
    assert.equal(await map.locator('[data-kind=memory]').count(), 2);
    assert.equal(await map.locator('[data-kind=history]').count(), 1);
    assert.equal(await map.locator('[data-relation=memory-source]').count(), 1);
    assert.equal(await map.locator('[data-relation=memory]').count(), 1);
    const vertical = await map.locator('[data-relation=memory]').evaluate(edge => {
      const host = edge.closest('.wb-run-mindmap');
      const source = [...host.querySelectorAll('[data-mindmap-node]')].find(node => node.dataset.mindmapNode === edge.dataset.from);
      const matrix = new DOMMatrix(source.style.transform);
      const start = edge.querySelector('path').getAttribute('d').match(/^M ([-\d.e+]+) ([-\d.e+]+)/);
      return Math.abs(Number(start[2]) - matrix.f - Number.parseFloat(source.style.height)) < 0.01;
    });
    assert.ok(vertical, 'RUN to a lower reference leaves the RUN bottom boundary');
    const unconfirmed = card(page, evidence.run_memory.id);
    const unconfirmedKey = await unconfirmed.getAttribute('data-mindmap-node');
    assert.equal(await map.locator('[data-from][data-to]').evaluateAll((edges, key) => edges.filter(edge =>
      edge.dataset.from === key || edge.dataset.to === key).length, unconfirmedKey), 0);
    assert.equal(await map.locator('[data-relation] .wb-mm-flow').count(), 0, 'reference edges never claim execution');
    const runKey = await map.getAttribute('data-run-key');
    await jump(page, 'memory');
    await card(page, evidence.item_memory.id).locator('button').click();
    await page.locator('.wb-memory-note').waitFor();
    await back(page, runKey);
    assert.equal(await map.getAttribute('data-run-key'), runKey);
    await jump(page, 'history');
    await map.locator('[data-kind=history] button').click();
    await page.getByText('Original archived record', { exact: true }).waitFor();
    await back(page, runKey);
    assert.equal(await map.getAttribute('data-run-key'), runKey);
    assert.equal(runPython(context + `with sqlite3.connect(app._db_path) as conn:
 print(json.dumps(conn.execute("SELECT count(*) FROM events WHERE event_type='run_references_updated'").fetchone()[0]))`), evidence.events);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('associative-memory SVG connections also stay in central 35% side bands', async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  try {
    await page.goto(origin); await page.waitForLoadState('networkidle');
    await page.locator('[data-wb-focus="nav:memories"]').click();
    await page.locator('.wb-memory-mindmap').waitFor();
    await assertSideBands(page, '.wb-memory-mindmap');
  } finally { await page.close(); }
});

test('opened RUN references navigate and return; palette and follow keep workflow context', async () => {
  runPython(context + `app.get_run(${JSON.stringify(evidence.run_memory.source.run_id)},source_db=${JSON.stringify(evidence.run_memory.source_db)})
print('true')`);
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'en-US', reducedMotion: 'reduce' });
  try {
    await page.goto(origin); await page.waitForLoadState('networkidle');
    const map = page.locator('.wb-run-mindmap'); await map.waitFor();
    assert.equal(await map.locator('[data-kind=history]').count(), 2);
    assert.equal(await map.locator('[data-relation=memory-source]').count(), 2);
    const runKey = await map.getAttribute('data-run-key');
    const follow = map.locator('[data-wb-focus=mindmap-follow]');
    assert.equal(await follow.getAttribute('aria-label'), 'Follow RUN and active work');
    const framing = await map.evaluate(el => {
      const view = el.getBoundingClientRect();
      const nodes = [...el.querySelectorAll('[data-kind=run], [data-kind=task]:has(button[data-status="In Progress"])')];
      return nodes.every(node => { const r=node.getBoundingClientRect(); return r.left >= view.left && r.right <= view.right && r.top >= view.top && r.bottom <= view.bottom; });
    });
    assert.ok(framing, 'RUN and all executing TASKs remain framed without reference band');
    await jump(page, 'history');
    const target = map.locator('[data-kind=history]').filter({ has: page.locator('.wb-mm-reference-origin', { hasText: /^RUN/ }) });
    await target.locator('button').click();
    await page.waitForFunction(key => {
      const map = document.querySelector('.wb-run-mindmap');
      return map && map.dataset.runKey !== key;
    }, runKey);
    await back(page, runKey);
    assert.equal(await map.getAttribute('data-run-key'), runKey);
    await jump(page, 'memory');
    for (const theme of ['light', 'dark']) {
      await page.locator('html').evaluate((el, value) => { el.dataset.taplTheme = value; }, theme);
      const colors = await map.evaluate(el => ['memory', 'history'].map(kind => {
        const node = el.querySelector(`[data-kind=${kind}]`);
        return getComputedStyle(node).getPropertyValue('--mm-reference').trim();
      }));
      assert.ok(colors.every(Boolean)); assert.notEqual(colors[0], colors[1]);
      if (process.env.TAPL_SCREENSHOT_DIR) {
        mkdirSync(process.env.TAPL_SCREENSHOT_DIR, { recursive: true });
        await page.screenshot({ path: path.join(process.env.TAPL_SCREENSHOT_DIR, `run-references-${theme}.png`), animations: 'disabled' });
      }
    }
  } finally { await page.close(); }
});

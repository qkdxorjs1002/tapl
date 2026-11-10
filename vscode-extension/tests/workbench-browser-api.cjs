const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const path = require('node:path');
const { buildSync } = require('esbuild');
const output = buildSync({ entryPoints: [path.join(__dirname, '../src/webview/vscodeApi.ts')],
  bundle: true, write: false, platform: 'browser', format: 'cjs' }).outputFiles[0].text;
const tick = () => new Promise(resolve => setImmediate(resolve));
const overview = { type: 'overview', archives: [], searchQuery: '', status: { session_id: 'active-owner', source_db: 'tapl-local.db',
  active_run: { id: 'active', session_id: 'active-owner' }, plans: [], tasks: [], findings: [] } };
const run = { type: 'run', snapshot: { run: { id: 'past', session_id: 'past-owner', status: 'archived', source_db: 'tapl-peer.db' }, readonly: true } };
const records = { type: 'records', query: '50%_', scope: 'run', runId: 'past', source_db: 'tapl-peer.db', offset: 50, limit: 15,
  total: 65, records: [], runs: [], context: run.snapshot };
const reply = view => ({ type: 'view:update', locale: 'en', layout: 'auto', workspace: '/work', capabilities: { associativeMemory: true, discardRun: true }, view });

function harness(initial) {
  const calls = [], messages = [], pending = [], timers = new Map();
  const storage = () => { const data = new Map(); return { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) }; };
  const localStorage = storage(), sessionStorage = storage();
  localStorage.setItem('tapl.viewer.workspace.v1', JSON.stringify('/work'));
  if (initial) sessionStorage.setItem('tapl.viewer.state.v1', JSON.stringify(initial));
  let api, timerId = 0;
  const context = vm.createContext({ module: { exports: {} }, Error, localStorage, sessionStorage, navigator: { language: 'en' },
    document: { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} },
    MessageEvent: class { constructor(type, options) { this.type = type; this.data = options.data; } },
    window: { setTimeout(fn) { timers.set(++timerId, fn); return timerId; }, clearTimeout(id) { timers.delete(id); }, dispatchEvent(event) {
      messages.push(event.data);
      if (event.data.view) api.setState({ view: event.data.view, workspace: event.data.workspace, capabilities: event.data.capabilities, locale: 'en', layout: 'auto' });
    } },
    fetch(url, options) { calls.push({ url, request: JSON.parse(options.body) }); return new Promise((resolve, reject) => pending.push({ resolve, reject })); }
  });
  vm.runInContext(output, context);
  api = context.module.exports.vscodeApi();
  async function resolve(payload) {
    assert.ok(pending.length);
    pending.shift().resolve({ ok: true, async json() { return payload; } });
    await tick(); await tick();
  }
  return { api, calls, messages, pending, timers, resolve, sessionStorage };
}

test('browser exact routes preserve source/page and active owner across refresh/back', async () => {
  const h = harness();
  h.api.postMessage({ command: 'ready' }); await h.resolve(reply(overview));
  h.api.setState({ ...h.api.getState(), workbench: { expanded: ['past'], custom: true } });
  h.api.postMessage({ command: 'openRun', runId: 'past', source_db: 'tapl-peer.db' }); await h.resolve(reply(run));
  assert.equal(h.api.getState().selectedSessionId, 'active-owner');
  assert.equal(h.api.getState().selectedSourceDb, 'tapl-local.db');
  assert.equal(h.api.getState().workbench.custom, true);
  h.api.postMessage({ command: 'refresh' });
  assert.equal(h.calls.at(-1).request.runId, 'past');
  assert.equal(h.calls.at(-1).request.source_db, 'tapl-peer.db');
  assert.equal(h.calls.at(-1).request.viewType, 'run');
  await h.resolve(reply(run));
  h.api.postMessage({ command: 'records', query: '50%_', scope: 'run', runId: 'past', source_db: 'tapl-peer.db', offset: 50, limit: 15 });
  await h.resolve(reply(records));
  h.api.postMessage({ command: 'refresh' });
  assert.deepEqual(h.calls.at(-1).request, { command: 'refresh', sessionId: 'active-owner', workspace: '/work', locale: 'en', layout: 'auto',
    viewType: 'records', query: '50%_', scope: 'run', runId: 'past', source_db: 'tapl-peer.db', offset: 50, limit: 15 });
  await h.resolve(reply(records));
  h.api.postMessage({ command: 'openSearchResult', itemId: 1, source_db: 'tapl-peer.db' });
  await h.resolve(reply({ type: 'searchItem', result: { id: 1, run_id: 'past', source_db: 'tapl-peer.db' }, context: run.snapshot }));
  h.api.postMessage({ command: 'back' });
  assert.equal(h.calls.at(-1).request.offset, 50);
  assert.equal(h.calls.at(-1).request.viewType, 'records');
  await h.resolve(reply(records));
  h.api.postMessage({ command: 'records' });
  assert.equal(h.calls.at(-1).request.source_db, undefined, 'all scope must not inherit selected source');
  await h.resolve(reply({ ...records, scope: 'all', runId: undefined, source_db: undefined, offset: 0 }));
  h.api.postMessage({ command: 'openRun', runId: 'local' });
  assert.equal(h.calls.at(-1).request.source_db, undefined, 'omitted exact-read selector means local history');
});

test('browser reload restores the exact record page rather than selecting its former session', async () => {
  const h = harness({ view: records, workspace: '/work', selectedSessionId: 'active-owner', selectedSourceDb: 'tapl-local.db' });
  h.api.postMessage({ command: 'ready' });
  await h.resolve(reply(overview));
  assert.equal(h.calls.at(-1).request.command, 'refresh');
  assert.equal(h.calls.at(-1).request.runId, 'past');
  assert.equal(h.calls.at(-1).request.source_db, 'tapl-peer.db');
  assert.equal(h.calls.at(-1).request.offset, 50);
  await h.resolve(reply(records));
  assert.equal(h.api.getState().view.type, 'records');
  assert.equal(h.api.getState().selectedSessionId, 'active-owner');
});

test('revision polling refreshes exact selectors and stale pages cannot overwrite navigation', async () => {
  const h = harness();
  h.api.postMessage({ command: 'ready' }); await h.resolve(reply(overview));
  h.api.postMessage({ command: 'records', query: '50%_', scope: 'run', runId: 'past', source_db: 'tapl-peer.db', offset: 50, limit: 15 });
  await h.resolve(reply(records));
  h.api.setPollingActive(true);
  const [timerId, poll] = [...h.timers.entries()][0]; h.timers.delete(timerId); poll();
  assert.equal(h.calls.at(-1).request.command, 'revision');
  await h.resolve({ type: 'revision', workspace: '/work', workspaceValid: true, revision: 'changed', message: '' });
  assert.equal(h.calls.at(-1).request.viewType, 'records');
  assert.equal(h.calls.at(-1).request.offset, 50);
  const stale = h.pending.shift();
  h.api.postMessage({ command: 'openRun', runId: 'past', source_db: 'tapl-peer.db' });
  await h.resolve(reply(run));
  stale.resolve({ ok: true, async json() { return reply(records); } });
  await tick(); await tick();
  assert.equal(h.api.getState().view.type, 'run');
  assert.equal(h.api.getState().selectedSessionId, 'active-owner');
  h.api.setPollingActive(false);
});

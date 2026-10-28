const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const path = require('node:path');
const { buildSync } = require('esbuild');
const output = buildSync({ entryPoints: [path.join(__dirname, '../src/webview/vscodeApi.ts')],
  bundle: true, write: false, platform: 'browser', format: 'cjs' }).outputFiles[0].text;
const tick = () => new Promise(resolve => setImmediate(resolve));
const board = (owner = 'a', owners = ['a', 'b']) => ({ type: 'overview', workspace: '/work/first', archives: [], searchQuery: '',
  status: { session_id: owner, active_run: { id: `run-${owner}`, session_id: owner },
    active_runs: owners.map(id => ({ id: `run-${id}`, session_id: id })), plans: [], tasks: [], findings: [] } });
const reply = (view = board(), extra = {}) => ({ type: 'view:update', locale: 'en', layout: 'auto', workspace: view.workspace,
  capabilities: { associativeMemory: true, discardRun: true }, view, ...extra });
const discard = (extra = {}) => ({ command: 'discardRun', runId: 'run-b', targetSessionId: 'b', workspace: '/work/first', confirmed: true, confirmationRunId: 'run-b', ...extra });
function harness() {
  const calls = [], messages = [], pending = [];
  const storage = () => { const values = new Map(); return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }; };
  const localStorage = storage(), sessionStorage = storage();
  localStorage.setItem('tapl.viewer.workspace.v1', JSON.stringify('/work/first'));
  let api;
  const context = vm.createContext({ module: { exports: {} }, Error, localStorage, sessionStorage,
    navigator: { language: 'en' }, document: { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} },
    MessageEvent: class { constructor(type, options) { this.type = type; this.data = options.data; } },
    window: { setTimeout() { return 1; }, clearTimeout() {}, dispatchEvent(event) {
      messages.push(event.data);
      if (event.data.view) api.setState({ view: event.data.view, workspace: event.data.workspace,
        capabilities: event.data.capabilities, locale: 'en', layout: 'auto' });
    } },
    fetch(url, options) { calls.push({ url, ...options, request: JSON.parse(options.body) });
      return new Promise((resolve, reject) => pending.push({ resolve, reject })); }
  });
  vm.runInContext(output, context);
  api = context.module.exports.vscodeApi();
  const resolve = async (payload, ok = true, status = 200) => {
    assert.ok(pending.length, 'expected an in-flight request');
    pending.shift().resolve({ ok, status, async json() { return payload; } });
    await tick(); await tick();
  };
  return { api, calls, messages, pending, resolve, sessionStorage };
}
async function ready(h) { h.api.postMessage({ command: 'ready' }); await h.resolve(reply()); }

test('browser discard sends captured target and workspace, keeps selected owner, and avoids history replay', async () => {
  const h = harness(); await ready(h);
  h.api.postMessage(discard());
  assert.equal(h.calls.at(-1).method, 'POST');
  assert.deepEqual({ ...h.calls.at(-1).request }, { ...discard(), sessionId: 'a', locale: 'en', layout: 'auto' });
  await h.resolve(reply(board('a', ['a']), { discardResult: { runId: 'run-b', ok: true } }));
  assert.equal(h.api.getState().selectedSessionId, 'a');
  assert.deepEqual(JSON.parse(h.sessionStorage.getItem('tapl.viewer.history.v1') ?? '[]'), []);
  const count = h.calls.length;
  h.api.postMessage({ command: 'back' });
  assert.equal(h.calls.length, count + 1);
  assert.equal(h.calls.at(-1).request.command, 'ready');
  assert.equal(h.calls.filter(call => call.request.command === 'discardRun').length, 1);
});

test('browser rejects malformed confirmation, target, unsupported host and workspace without network writes', async () => {
  const h = harness(); await ready(h);
  const count = h.calls.length;
  for (const change of [{ confirmed: false }, { confirmed: 1 }, { confirmed: 'true' }, { confirmationRunId: undefined }, { confirmationRunId: '' },
    { confirmationRunId: 'run-' }, { confirmationRunId: 'RUN-B' }, { confirmationRunId: 'run-b ' },
    { confirmationRunId: ' run-b' }, { confirmationRunId: 1 }, { workspace: '/work/second' },
    { targetSessionId: undefined }, { targetSessionId: 'b\n' }, { runId: '' }]) {
    h.api.postMessage(discard(change));
    assert.equal(h.messages.at(-1).discardResult.ok, false);
  }
  h.api.setState({ view: board(), workspace: '/work/first', capabilities: { associativeMemory: true } });
  h.api.postMessage(discard());
  assert.equal(h.calls.length, count);
});

test('browser keeps mutation errors on the current board even after selection changes', async () => {
  const h = harness(); await ready(h);
  h.api.postMessage(discard());
  h.api.postMessage({ command: 'selectRun', sessionId: 'c' });
  const mutation = h.pending.shift();
  await h.resolve(reply(board('c')));
  mutation.resolve({ ok: true, async json() { return { type: 'error', message: 'stale_run', locale: 'en', layout: 'auto',
    discardResult: { runId: 'run-b', ok: false, message: 'stale_run' } }; } });
  await tick(); await tick();
  assert.equal(h.messages.at(-1).discardResult.message, 'stale_run');
  assert.equal(h.api.getState().view.status.session_id, 'c');
  assert.equal(h.api.getState().selectedSessionId, 'c');
});

test('browser ignores stale mutation overview, resolves the result, and preserves newer selection', async () => {
  const h = harness(); await ready(h);
  h.api.postMessage(discard());
  const mutation = h.pending.shift();
  h.api.postMessage({ command: 'selectRun', sessionId: 'c' });
  await h.resolve(reply(board('c')));
  mutation.resolve({ ok: true, async json() { return reply(board('a', ['a']), { discardResult: { runId: 'run-b', ok: true } }); } });
  await tick(); await tick();
  assert.equal(h.messages.at(-1).discardResult.ok, true);
  assert.equal(h.messages.at(-1).view, undefined);
  assert.equal(h.api.getState().selectedSessionId, 'c');
});

test('browser does not deliver old workspace mutation replies and wraps transport errors with a result', async () => {
  const h = harness(); await ready(h);
  h.api.postMessage(discard());
  const mutation = h.pending.shift();
  h.api.postMessage({ command: 'selectWorkspace', workspace: '/work/second' });
  await h.resolve(reply({ ...board('z'), workspace: '/work/second' }));
  const count = h.messages.length;
  mutation.reject(new Error('old workspace failed'));
  await tick(); await tick();
  assert.equal(h.messages.length, count);
  const callCount = h.calls.length;
  h.api.postMessage(discard());
  assert.equal(h.calls.length, callCount, 'a dialog captured in the previous workspace cannot send a mutation');
  assert.equal(h.messages.at(-1).discardResult.ok, false);
  h.api.postMessage(discard({ workspace: '/work/second', runId: 'run-z', targetSessionId: 'z', confirmationRunId: 'run-z' }));
  h.pending.shift().reject(new Error('connection lost'));
  await tick(); await tick();
  assert.equal(h.messages.at(-1).discardResult.message, 'connection lost');
  assert.equal(h.api.getState().workspace, '/work/second');
});

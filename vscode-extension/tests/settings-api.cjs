const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const path = require('node:path');
const { buildSync } = require('esbuild');
const output = buildSync({ entryPoints: [path.join(__dirname, '../src/webview/vscodeApi.ts')],
  bundle: true, write: false, platform: 'browser', format: 'cjs' }).outputFiles[0].text;
const tick = () => new Promise(resolve => setImmediate(resolve));
const settings = { path: '/work/config.toml', exists: true, revision: 'r1', fields: [], values: {}, defaults: {}, overrides: {} };
const view = { type: 'run', snapshot: { run: { id: 'archived', session_id: 'past', source_db: 'peer.db' } } };
function harness(restored = {}, language = 'en') {
  const calls = [], messages = [], pending = [], timers = new Map();
  const storage = () => { const data = new Map(); return { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) }; };
  const localStorage = storage(), sessionStorage = storage();
  sessionStorage.setItem('tapl.viewer.state.v1', JSON.stringify({ workspace: '/work', view, selectedSessionId: 'selected-owner', selectedSourceDb: 'peer.db', ...restored }));
  const context = vm.createContext({ module: { exports: {} }, Error, localStorage, sessionStorage, navigator: { language },
    document: { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} },
    MessageEvent: class { constructor(_type, options) { this.data = options.data; } },
    window: { setTimeout(fn) { const key = timers.size + 1; timers.set(key, fn); return key; }, clearTimeout(id) { timers.delete(id); },
      dispatchEvent(event) { messages.push(event.data); } },
    fetch(_url, options) { calls.push(JSON.parse(options.body)); return new Promise((resolve, reject) => pending.push({ resolve, reject })); }
  });
  vm.runInContext(output, context);
  const api = context.module.exports.vscodeApi();
  const resolve = async (payload, request = pending.shift()) => { request.resolve({ ok: true, async json() { return payload; } }); await tick(); await tick(); };
  const result = (requestId, extra = {}) => ({ type: 'settings:result', requestId, workspace: '/work', ok: true, settings, ...extra });
  return { api, calls, messages, pending, timers, resolve, result };
}

test('settings requests never inherit RUN selectors or replace the browser route; save/reset validate revision and confirmation', async () => {
  const h = harness(), before = JSON.stringify(h.api.getState());
  h.api.postMessage({ command: 'getSettings', requestId: 'get' });
  assert.deepEqual(h.calls[0], { command: 'getSettings', requestId: 'get', workspace: '/work', locale: 'en' });
  await h.resolve(h.result('get'));
  assert.equal(JSON.stringify(h.api.getState()), before);
  const save = { command: 'saveSettings', requestId: 'save', workspace: '/work', revision: 'r1', values: { 'logging.enabled': false } };
  for (const invalid of [{ workspace: '/other' }, { revision: 'old' }, { values: [] }]) {
    h.api.postMessage({ ...save, ...invalid }); assert.equal(h.messages.at(-1).ok, false);
  }
  assert.equal(h.calls.length, 1);
  h.api.postMessage(save);
  h.api.postMessage({ ...save, requestId: 'concurrent' });
  assert.equal(h.messages.at(-1).code, 'busy'); assert.equal(h.calls.length, 2);
  await h.resolve(h.result('save', { settings: { ...settings, revision: 'r2' }, changed: true }));
  h.api.postMessage({ command: 'resetSettings', requestId: 'reset', workspace: '/work', revision: 'r2', confirmed: false });
  assert.equal(h.messages.at(-1).code, 'invalid_request');
  h.api.postMessage({ command: 'resetSettings', requestId: 'reset', workspace: '/work', revision: 'r2', confirmed: true });
  assert.equal(h.calls.at(-1).command, 'resetSettings');
  await h.resolve(h.result('reset'));
  assert.equal(h.messages.at(-1).action, 'reset');
  assert.equal(JSON.stringify(h.api.getState()), before);
});

test('settings supersede stale reads, survive route navigation, reject old servers and drop old workspace replies', async () => {
  const h = harness();
  h.api.postMessage({ command: 'getSettings', requestId: 'old' }); const old = h.pending.shift();
  h.api.postMessage({ command: 'getSettings', requestId: 'new' });
  await h.resolve(h.result('new')); const count = h.messages.length;
  await h.resolve(h.result('old'), old); assert.equal(h.messages.length, count);
  h.api.postMessage({ command: 'getSettings', requestId: 'navigate' }); const duringNavigation = h.pending.shift();
  h.api.postMessage({ command: 'openRun', runId: 'next' });
  await h.resolve(h.result('navigate'), duringNavigation);
  assert.equal(h.messages.at(-1).requestId, 'navigate');
  await h.resolve({ type: 'view:update', view, workspace: '/work', locale: 'en', layout: 'auto' });
  h.api.postMessage({ command: 'getSettings', requestId: 'unsupported' });
  await h.resolve({ type: 'error', message: 'Unknown command' });
  assert.equal(h.messages.at(-1).code, 'unsupported');
  assert.equal(h.api.getState().view.type, 'run');
  h.api.postMessage({ command: 'getSettings', requestId: 'previous-workspace' }); const previous = h.pending.shift();
  h.api.postMessage({ command: 'selectWorkspace', workspace: '/next' });
  await h.resolve({ type: 'view:update', view: { type: 'overview' }, workspace: '/next', locale: 'en', layout: 'auto' });
  const switched = h.messages.length; await h.resolve(h.result('previous-workspace'), previous);
  assert.equal(h.messages.length, switched);
});

test('pending settings pause polling refresh and failures stay inline', async () => {
  const h = harness(); h.api.setPollingActive(true);
  h.api.postMessage({ command: 'getSettings', requestId: 'get' });
  assert.equal(h.timers.size, 0);
  h.api.postMessage({ command: 'refresh' }); assert.equal(h.calls.length, 1);
  h.pending.shift().reject(new Error('Offline')); await tick(); await tick();
  assert.equal(h.messages.at(-1).type, 'settings:result'); assert.equal(h.messages.at(-1).message, 'Offline');
  assert.equal(h.api.getState().view.type, 'run'); assert.equal(h.timers.size, 1);
});


test('settings and navigation send system locale and keep authoritative preferences without changing the route', async () => {
  const h = harness({ userLocale: 'en', locale: 'en', layout: 'small' }, 'ko-KR');
  h.api.postMessage({ command: 'getSettings', requestId: 'get' });
  assert.equal(h.calls[0].locale, 'ko-KR'); assert.equal(h.calls[0].layout, undefined);
  const preferences = { language: 'auto', layout: 'large', mcp_path: '/custom/tapl-mcp' };
  await h.resolve(h.result('get', { locale: 'ko', layout: 'large', preferences }));
  assert.equal(h.api.getState().view.type, 'run'); assert.equal(h.api.getState().locale, 'ko');
  assert.equal(h.api.getState().layout, 'large'); assert.equal(h.api.getState().preferences.mcp_path, preferences.mcp_path);
  h.api.postMessage({ command: 'saveSettings', requestId: 'save', workspace: '/work', revision: 'r1', values: { 'viewer.language': 'en' } });
  assert.equal(h.calls.at(-1).locale, 'ko-KR');
  await h.resolve(h.result('save', { locale: 'en', layout: 'auto', preferences: { ...preferences, language: 'en', layout: 'auto' } }));
  h.api.postMessage({ command: 'resetSettings', requestId: 'reset', workspace: '/work', revision: 'r1', confirmed: true });
  assert.equal(h.calls.at(-1).locale, 'ko-KR');
  await h.resolve(h.result('reset', { locale: 'ko', layout: 'auto', preferences: { language: 'auto', layout: 'auto', mcp_path: '' } }));
  assert.equal(h.api.getState().locale, 'ko');
  h.api.postMessage({ command: 'openRun', runId: 'next' });
  assert.equal(h.calls.at(-1).locale, 'ko-KR'); assert.equal(h.calls.at(-1).layout, undefined);
  await h.resolve({ type: 'view:update', view, workspace: '/work', locale: 'en', layout: 'medium', preferences });
  assert.equal(h.api.getState().locale, 'en'); assert.equal(h.api.getState().layout, 'medium');
});

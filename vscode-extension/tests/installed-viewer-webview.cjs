const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const path = require('node:path');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { buildSync } = require('esbuild');
const { version: extensionVersion } = require('../package.json');

const ctlVersion = '9.8.7-beta.1';
const output = buildSync({
  stdin: { contents: "export { App } from './src/webview/App'; export { vscodeApi } from './src/webview/vscodeApi';",
    resolveDir: path.join(__dirname, '..') },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', loader: { '.css': 'empty' },
  external: ['react', 'react-dom'], define: { __TAPL_CTL_RELEASE_TAG__: JSON.stringify(ctlVersion) }
}).outputFiles[0].text;
const channel = '1234567890abcdef'.repeat(2);
const otherChannel = 'fedcba0987654321'.repeat(2);
const tick = () => new Promise(resolve => setImmediate(resolve));

const overview = (runId, sessionId, source_db) => ({
  type: 'overview', archives: [], searchQuery: '', status: {
    active_run: { id: runId, session_id: sessionId, source_db },
    session_id: sessionId, source_db, tasks: [], plans: [], findings: [], recent_events: [], schema: {}
  }
});
const exactRun = { type: 'run', snapshot: { run: { id: 'archived', session_id: 'archived-owner', source_db: 'tapl-peer.db' } } };
const view = (view, workspace = '/selected') => ({
  type: 'view:update', view, workspace, locale: 'en', layout: 'auto', capabilities: { associativeMemory: true, discardRun: true }
});

function harness({ native = true, meta = true } = {}) {
  const calls = [], stateWrites = [], timers = new Map();
  const savedState = { workspace: '/last-editor', workbenchWorkspace: '/last-editor', workbench: { theme: 'dark' } };
  const storage = values => ({ getItem: key => values[key] ?? null, setItem(key, value) { values[key] = value; } });
  const window = new EventTarget();
  let timerId = 0;
  window.setTimeout = (run, delay) => { timers.set(++timerId, { run, delay }); return timerId; };
  window.clearTimeout = id => timers.delete(id);
  window.localStorage = storage({ 'tapl.viewer.workspace.v1': JSON.stringify('/last-browser') });
  window.location = { protocol: 'http:', hostname: 'localhost', hash: '#workspace=%2Fbrowser-link' };
  const environment = vm.createContext({ module: { exports: {} }, require, MessageEvent, URLSearchParams, matchMedia: () => ({ matches: false }),
    navigator: { language: 'en' }, localStorage: window.localStorage, sessionStorage: storage({}), Error,
    document: { visibilityState: 'visible', body: { classList: { contains: () => false } },
      querySelector: selector => meta ? { content: selector.includes('protocol') ? '1' : channel } : null },
    ...(native && { acquireVsCodeApi: () => ({ postMessage: message => calls.push(message),
      getState: () => savedState, setState: state => stateWrites.push(state) }) }),
    fetch() { throw new Error('Unexpected HTTP Viewer request'); }
  });
  vm.runInContext(output, environment);
  environment.window = window;
  const { vscodeApi, App } = environment.module.exports;
  const api = vscodeApi();
  const messages = [];
  api.subscribe?.(message => {
    messages.push(message);
    if ('view' in message) api.setState({ ...api.getState(), workspace: message.workspace, view: message.view, capabilities: message.capabilities });
  });
  const receive = data => window.dispatchEvent(new MessageEvent('message', { data }));
  const respond = (request, payload, responseChannel = channel) =>
    receive({ type: 'viewer:response', channel: responseChannel, requestId: request.requestId, payload });
  return { api, App, messages, calls, stateWrites, timers, receive, respond };
}

test('installed assets correlate replies and refresh the exact source and RUN through VS Code', async () => {
  const h = harness();
  assert.equal(h.api.installedViewer, true);
  h.api.postMessage({ command: 'ready' });
  const [ready] = h.calls;
  assert.equal(ready.command, 'viewerRequest');
  assert.equal(ready.protocol, 1);
  assert.equal(ready.channel, channel);
  assert.equal(ready.message.workspace, '');
  assert.equal(ready.message.sessionId, undefined);
  assert.equal(ready.message.runId, undefined);
  const initial = view(overview('active', 'active-owner', 'tapl-local.db'));
  h.receive(initial);
  h.respond(ready, initial, otherChannel);
  h.respond({ requestId: 'unknown' }, initial);
  await tick();
  assert.equal(h.messages.length, 0);
  h.respond(ready, initial);
  await tick();
  assert.equal(h.api.getState().workspace, '/selected');
  assert.equal(h.stateWrites.at(-1).workspace, '/selected');
  assert.equal(h.stateWrites.at(-1).view, undefined);
  assert.equal(h.stateWrites.at(-1).workbench.theme, 'dark');

  h.api.postMessage({ command: 'openRun', runId: 'archived', source_db: 'tapl-peer.db' });
  const open = h.calls.at(-1);
  assert.equal(open.message.workspace, '/selected');
  assert.notEqual(open.requestId, ready.requestId);
  h.respond(open, view(exactRun));
  await tick();
  h.api.postMessage({ command: 'refresh' });
  const refresh = h.calls.at(-1);
  assert.equal(refresh.message.viewType, 'run');
  assert.equal(refresh.message.sessionId, 'active-owner');
  assert.equal(refresh.message.source_db, 'tapl-peer.db');
  assert.equal(refresh.message.runId, 'archived');
  h.respond(refresh, view(exactRun));
  await tick();
  assert.equal(h.timers.size, 0);
});

test('native navigation and workspace reset discard old replies and host selectors', async () => {
  const h = harness();
  h.api.postMessage({ command: 'ready' });
  h.respond(h.calls.at(-1), view(overview('active', 'active-owner', 'tapl-local.db')));
  await tick();
  h.api.postMessage({ command: 'getSettings', requestId: 'read-settings', workspace: '/selected' });
  const oldSettings = h.calls.at(-1);
  h.api.postMessage({ command: 'openRun', runId: 'archived', source_db: 'tapl-peer.db' });
  const oldRun = h.calls.at(-1);
  const navigate = (target, message, reset) => h.receive({ type: 'viewer:navigate', channel: target, message, reset });
  navigate(otherChannel, { command: 'ready' }, true);
  assert.equal(h.calls.at(-1), oldRun);
  navigate(channel, { command: 'ready' }, true);
  const ready = h.calls.at(-1);
  assert.equal(ready.message.workspace, '');
  assert.equal(ready.message.source_db, undefined);
  assert.equal(ready.message.sessionId, undefined);
  h.respond(oldRun, view(exactRun));
  h.respond(oldSettings, { type: 'settings:result', requestId: 'read-settings', workspace: '/selected', ok: false });
  h.respond(ready, view(overview('new-run', 'new-owner', 'tapl-next.db'), '/next'));
  await tick();
  assert.equal(h.messages.length, 2);
  assert.equal(h.messages.at(-1).workspace, '/next');
  navigate(channel, { command: 'openArchive', archiveId: 'completed', source_db: 'tapl-peer.db' });
  const openArchive = h.calls.at(-1);
  assert.equal(openArchive.message.workspace, '/next');
  assert.equal(openArchive.message.sessionId, 'new-owner');
  assert.equal(openArchive.message.source_db, 'tapl-peer.db');
  h.respond(openArchive, view({ type: 'archive', archive: { id: 'completed', source_db: 'tapl-peer.db' } }, '/next'));
  await tick();
  assert.equal(h.messages.at(-1).view.type, 'archive');
});

test('native tour and workspace actions keep VS Code behavior while installed assets use the ctl release', async () => {
  const h = harness();
  h.api.postMessage({ command: 'ready' });
  h.respond(h.calls.at(-1), view({ type: 'workspace', workspace: '/unavailable', message: 'Workspace unavailable' }, ''));
  await tick();
  assert.deepEqual(JSON.parse(JSON.stringify(h.messages.at(-1).view)), { type: 'error', message: 'Workspace unavailable' });
  h.api.postMessage({ command: 'chooseWorkspace' });
  h.api.postMessage({ command: 'saveTourHistory', history: { intro: 'completed' } });
  assert.equal(h.calls.at(-2).command, 'chooseWorkspace');
  assert.equal(h.calls.at(-1).command, 'saveTourHistory');
  h.receive({ type: 'tour:history', history: { intro: 'completed' } });
  h.receive({ type: 'tour:open' });
  assert.equal(h.messages.at(-2).type, 'tour:history');
  assert.equal(h.messages.at(-1).type, 'tour:open');

  const installed = renderToStaticMarkup(React.createElement(h.App));
  assert.ok(installed.includes(`/releases/tag/${ctlVersion}`));
  assert.ok(!installed.includes('data-wb-focus="workspace-picker"'));
  const old = harness({ meta: false });
  old.api.postMessage({ command: 'ready' });
  assert.equal(old.calls[0].command, 'ready');
  const bundled = renderToStaticMarkup(React.createElement(old.App));
  assert.ok(bundled.includes(`/releases/tag/viewer-${extensionVersion}`));
  const browser = harness({ native: false });
  const browserHtml = renderToStaticMarkup(React.createElement(browser.App));
  assert.ok(browserHtml.includes(`/releases/tag/${ctlVersion}`));
  assert.ok(browserHtml.includes('data-wb-focus="workspace-picker"'));
});

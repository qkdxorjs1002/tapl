const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { buildSync } = require('esbuild');
const React = require('react');

const source = buildSync({
  entryPoints: [path.join(__dirname, '../src/webview/App.tsx')],
  bundle: true, platform: 'node', format: 'cjs', write: false, jsx: 'automatic', loader: { '.css': 'empty' },
  external: ['react', 'react/jsx-runtime', '../i18n', './i18n', './vscodeApi', './MemoryView', './workbench', './workbench/RecordDetail', './workbench/SecondaryViews', './workbench/Icon']
}).outputFiles[0].text;

function harness(restored, browser = false) {
  let cursor = 0, effects = [], reads = 0, saved = restored;
  const slots = [], writes = [], messages = [], listeners = new Map();
  const environment = { addEventListener: (type, handler) => listeners.set(type, handler), removeEventListener: type => listeners.delete(type) };
  const api = { getState: () => { reads++; return saved; }, setState: value => { saved = value; writes.push(value); }, postMessage: message => messages.push(message), ...(browser ? { setPollingActive() {} } : {}) };
  const memo = (compute, deps) => {
    const index = cursor++, previous = slots[index];
    if (!previous || !deps || deps.some((dep, i) => !Object.is(dep, previous.deps[i]))) slots[index] = { value: compute(), deps };
    return slots[index].value;
  };
  const react = { ...React,
    useRef: value => { const index = cursor++; return slots[index] ??= { current: value }; },
    useState: value => { const index = cursor++; if (!slots[index]) slots[index] = { value: typeof value === 'function' ? value() : value }; return [slots[index].value, next => { slots[index].value = typeof next === 'function' ? next(slots[index].value) : next; }]; },
    useEffect: (callback, deps) => memo(() => { effects.push(callback); }, deps)
  };
  const compiled = { exports: {} };
  new Function('module', 'exports', 'require', 'window', 'document', 'navigator', source)(compiled, compiled.exports, name => {
    if (name === 'react') return react;
    if (name === '../i18n' || name === './i18n') return { resolveLocale: value => value === 'ko' ? 'ko' : 'en', I18nProvider: () => null, useI18n: () => ({ t: value => value }) };
    if (name === './vscodeApi') return { vscodeApi: () => api };
    if (name === './workbench') return { Workbench: () => null };
    if (name === './MemoryView') return { MemoryView: () => null };
    if (name === './workbench/RecordDetail') return { RecordDetail: () => null };
    if (name === './workbench/SecondaryViews') return { SecondaryView: () => null };
    if (name === './workbench/Icon') return { Icon: () => null };
    return require(name);
  }, environment, { documentElement: {} }, { language: 'en-US' });
  return { writes, messages, get reads() { return reads; }, render() {
    cursor = 0; effects = [];
    const tree = compiled.exports.App(); effects.forEach(effect => effect());
    return tree.props.children.props.children.props;
  }, receive(message) { listeners.get('message')({ data: message }); } };
}

const update = (view, workspace = '/one') => ({ type: 'view:update', workspace, locale: 'ko', layout: 'medium', preferences: { language: 'ko', layout: 'medium', mcp_path: '' }, capabilities: { associativeMemory: true, discardRun: true }, view });

test('native App reads saved state once, hydrates legacy view and stores only deduplicated UI state', () => {
  const legacyView = { type: 'error', message: 'legacy ' + 'x'.repeat(100000) };
  const app = harness({ view: legacyView, capabilities: { associativeMemory: true }, workspace: '/one', workbenchWorkspace: '/one', workbench: { version: 1, theme: 'dark', pinned: true }, userLocale: 'en', unexpected: 'legacy payload' });
  const initial = app.render();
  assert.equal(initial.view, legacyView);
  assert.deepEqual(app.messages, [{ command: 'ready' }]);
  const current = { type: 'error', message: 'current' };
  app.receive({ ...update(current), type: 'hydrate' });
  assert.equal(app.render().view, current);
  assert.equal(app.reads, 1);
  assert.deepEqual(Object.keys(app.writes[0]).sort(), ['layout', 'locale', 'preferences', 'workbench', 'workbenchWorkspace', 'workspace']);
  assert.ok(JSON.stringify(app.writes[0]).length < 500, 'large legacy view and capabilities are removed');
  const count = app.writes.length;
  for (let i = 0; i < 5; i++) { app.receive(update({ type: 'error', message: `refresh ${i}` })); app.render(); }
  assert.equal(app.writes.length, count, 'view-only refreshes do not serialize native state');
  const workbench = { version: 1, theme: 'light', pinned: true };
  app.render().onStateChange(workbench); app.render().onStateChange(structuredClone(workbench));
  assert.equal(app.writes.length, count + 1, 'equal UI state is also deduplicated');
});

test('native workspace switches retain theme and clear workspace-specific navigation', () => {
  const app = harness({ workspace: '/one', workbenchWorkspace: '/one', workbench: { version: 1, theme: 'dark', route: { type: 'item', id: 12 } } });
  app.render(); app.receive(update({ type: 'error', message: 'second workspace' }, '/two'));
  const state = app.render();
  assert.equal(state.workspace, '/two'); assert.deepEqual(state.initialState, { version: 1, theme: 'dark' });
  assert.deepEqual(app.writes.at(-1).workbench, { version: 1, theme: 'dark' });
  assert.equal(app.writes.at(-1).workbenchWorkspace, '/two'); assert.equal(app.reads, 1);
  const mismatch = harness({ workspace: '/two', workbenchWorkspace: '/one', workbench: { theme: 'light', route: { type: 'item' } } });
  assert.deepEqual(mismatch.render().initialState, { version: 1, theme: 'light' });
});

test('browser App retains full refreshed view and capabilities for BrowserApi route and request restoration', () => {
  const app = harness({ workspace: '/one', selectedSessionId: 'session', userLocale: 'legacy' }, true);
  app.render();
  const view = { type: 'error', message: 'browser live view' };
  app.receive(update(view)); app.render();
  assert.equal(app.writes.at(-1).view, view);
  assert.equal(app.writes.at(-1).selectedSessionId, 'session');
  assert.equal(app.writes.at(-1).capabilities.associativeMemory, true);
  assert.equal('userLocale' in app.writes.at(-1), false);
});

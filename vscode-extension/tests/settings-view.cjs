const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const fs = require('node:fs');
const { buildSync } = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const filename = path.join(__dirname, 'settings-render.cjs');
const output = buildSync({ loader: { '.css': 'empty' }, stdin: { loader: 'tsx',
  contents: fs.readFileSync(path.resolve(__dirname, '../src/webview/workbench/SettingsView.tsx'), 'utf8') + "\nexport { ModelsEditor, SettingEditor, SettingsConfirmation }; export { I18nProvider } from '../i18n'; export * as model from './model';",
  resolveDir: path.resolve(__dirname, '../src/webview/workbench')
}, bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react-dom'] }).outputFiles[0].text;
function load(react = React) {
  const compiled = new Module(filename, module); compiled.filename = filename; compiled.paths = module.paths;
  compiled.require = name => name === 'react' ? react : module.require(name);
  compiled._compile(output, filename); return compiled.exports;
}
const fields = [
  { key: 'recall.enabled', section: 'recall', type: 'boolean', description: 'Automatic memory.' },
  { key: 'search.max_results', section: 'search', type: 'integer', min: 1, description: 'Maximum results.' },
  { key: 'viewer.allowed_origins', section: 'viewer', type: 'string-list', description: 'Origins.' },
  { key: 'subagents.models', section: 'subagents', type: 'models', description: 'Models.' },
  { key: 'subagents.profiles', section: 'subagents', type: 'profiles', description: 'Profiles.' },
  { key: 'viewer.language', section: 'viewer', type: 'select', description: 'Language.', allowed: ['auto', 'ko', 'en'] },
  { key: 'viewer.layout', section: 'viewer', type: 'select', description: 'Layout.', allowed: ['auto', 'small', 'medium', 'large'] },
  { key: 'viewer.mcp_path', section: 'viewer', type: 'string', description: 'Server path.' }
];
const settings = { path: '/workspace/.tapl/config.toml', exists: true, revision: 'one', fields,
  values: { 'recall.enabled': true, 'search.max_results': 12, 'viewer.allowed_origins': [], 'subagents.models': { 'model.with.dots': ['high'], second: ['low'] }, 'subagents.profiles': [], 'viewer.language': 'auto', 'viewer.layout': 'auto', 'viewer.mcp_path': '' },
  defaults: { 'recall.enabled': true, 'search.max_results': 12, 'viewer.allowed_origins': [], 'subagents.models': {}, 'subagents.profiles': [], 'viewer.language': 'auto', 'viewer.layout': 'auto', 'viewer.mcp_path': '' }, overrides: ['subagents.models'], restart_required: ['viewer.allowed_origins'] };
function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
function harness(overrides = {}, getComponent = api => api.SettingsView) {
  const slots = []; let cursor = 0, dirty = false, effects = [], tree;
  const commands = [];
  const props = { active: true, workspace: '/workspace', send: value => commands.push(value), ...overrides };
  const react = { ...React, useContext: context => context._currentValue,
    useRef: value => { const i = cursor++; return slots[i] ??= { current: value }; },
    useState: initial => { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return [slots[i], value => { const next = typeof value === 'function' ? value(slots[i]) : value; if (!Object.is(next, slots[i])) { slots[i] = next; dirty = true; } }]; },
    useEffect: (effect, deps) => { const i = cursor++, previous = slots[i]; if (previous && deps?.every((value, n) => Object.is(value, previous.deps?.[n]))) return; effects.push(() => { previous?.cleanup?.(); slots[i] = { deps, cleanup: effect() }; }); }
  };
  const api = load(react), Component = getComponent(api);
  function render(update = {}) {
    Object.assign(props, update); let passes = 0;
    do { dirty = false; cursor = 0; effects = []; tree = Component(props); for (const effect of effects) effect(); assert.ok(++passes < 15, 'effects settle'); } while (dirty);
  }
  const find = predicate => nodes(tree).find(predicate);
  const field = key => find(node => node.props?.field?.key === key);
  function respond(result = {}) { render({ result: { type: 'settings:result', requestId: commands.at(-1).requestId, workspace: props.workspace, ok: true, settings, ...result } }); }
  render();
  return { api, props, commands, render, respond, find, field, nodes: () => nodes(tree), cleanup() { for (const slot of slots) slot?.cleanup?.(); } };
}
function withHarness(overrides, action, component) { const h = harness(overrides, component); try { action(h); } finally { h.cleanup(); } }
const submit = h => h.find(node => node.type === 'form').props.onSubmit({ preventDefault() {} });

test('save payload includes only changed registry fields and excludes locale or metadata', () => {
  assert.deepEqual(load().changedSettings(settings, { ...settings.values, 'search.max_results': 30, locale: 'ko', path: '/evil' }), { 'search.max_results': 30 });
});
test('validation checks ranges, profiles and client-specific model semantics', () => {
  const { settingsValueError: validate } = load();
  for (const value of ['', 0, 1.2, Infinity]) assert.ok(validate(fields[1], value));
  assert.equal(validate(fields[1], 1), undefined); assert.ok(validate(fields[3], { any: [] }));
  const claude = { ...fields[3], key: 'clients.claude-code.subagents.models' };
  assert.equal(validate(claude, { inherit: [], sonnet: [] }), undefined); assert.ok(validate(claude, { inherit: ['high'] }));
  assert.equal(validate(fields[3], { 'vendor.model.v2': ['high', 'low'] }), undefined);
  assert.ok(validate(fields[3], { any: ['high', ' high '] }));
  const profile = { name: 'routine', characteristics: '', delegation_bias: 'prefer', candidates: [{ model: 'sonnet' }] };
  assert.ok(validate(fields[4], [profile]));
  assert.equal(validate({ ...fields[4], key: 'clients.claude-code.subagents.profiles' }, [profile]), undefined);
  assert.ok(validate(fields[4], [{ ...profile, candidates: [] }, { ...profile, candidates: [] }]));
});
test('loading is lazy and Viewer preferences use the shared draft and save flow', () => withHarness({ active: false }, h => {
  assert.deepEqual(h.commands, []); assert.equal(h.find(node => node.props?.id === 'settings-language'), undefined);
  h.render({ active: true }); assert.equal(h.commands[0].command, 'getSettings'); h.respond();
  for (const [key, value] of [['viewer.language', 'ko'], ['viewer.layout', 'large'], ['viewer.mcp_path', '/custom/tapl-mcp']]) h.field(key).props.onChange(value);
  h.render(); assert.equal(h.commands.length, 1); assert.equal(h.field('viewer.language').props.value, 'ko');
  h.render({ active: false }); h.render({ active: true }); assert.equal(h.commands.length, 1);
  submit(h); h.render(); assert.deepEqual(h.commands.at(-1).values, { 'viewer.language': 'ko', 'viewer.layout': 'large', 'viewer.mcp_path': '/custom/tapl-mcp' });
}));
test('save locks synchronously, preserves failures and ignores unrelated results', () => withHarness({}, h => {
  h.respond(); h.field('search.max_results').props.onChange(30); h.render();
  const handler = h.find(node => node.type === 'form').props.onSubmit;
  handler({ preventDefault() {} }); handler({ preventDefault() {} }); h.render();
  assert.equal(h.commands.length, 2); assert.deepEqual(h.commands[1].values, { 'search.max_results': 30 });
  assert.equal(h.find(node => node.type === 'fieldset').props.disabled, true);
  h.render({ result: { type: 'settings:result', requestId: 'another', workspace: '/workspace', ok: true, settings } });
  assert.equal(h.find(node => node.type === 'fieldset').props.disabled, true);
  h.respond({ ok: false, settings: undefined, code: 'invalid_settings', message: 'Database unavailable' });
  assert.equal(h.field('search.max_results').props.value, 30); assert.equal(h.find(node => node.type === 'fieldset').props.disabled, false);
  assert.ok(h.find(node => node.props?.role === 'alert')); h.render({ active: false }); h.render({ active: true });
  assert.equal(h.field('search.max_results').props.value, 30); submit(h); h.render(); assert.equal(h.commands.length, 3);
}));
test('stale revision retains draft and reload needs explicit replacement', () => withHarness({}, h => {
  h.respond(); h.field('search.max_results').props.onChange(24); h.render(); submit(h); h.render();
  h.respond({ ok: false, settings: undefined, code: 'settings_conflict', message: 'Configuration changed' });
  assert.equal(h.field('search.max_results').props.value, 24);
  assert.equal(h.find(node => node.type === 'button' && node.props.type === 'submit').props.disabled, true);
  const open = () => h.find(node => node.type === 'button' && node.props.children === 'Reload configuration').props.onClick();
  open(); h.render(); let confirmation = h.find(node => node.type?.name === 'SettingsConfirmation');
  assert.ok(confirmation); assert.equal(h.commands.length, 2); confirmation.props.close(); h.render();
  assert.equal(h.field('search.max_results').props.value, 24); open(); h.render();
  h.find(node => node.type?.name === 'SettingsConfirmation').props.accept(); h.render();
  assert.equal(h.commands.at(-1).command, 'getSettings'); h.respond({ settings: { ...settings, revision: 'two' } });
  assert.equal(h.field('search.max_results').props.value, 12);
}));
test('reset cancellation sends nothing; confirm uses captured workspace and revision once', () => withHarness({}, h => {
  h.respond(); const open = () => h.find(node => node.type === 'button' && node.props.children === 'Reset all to defaults').props.onClick();
  open(); h.render(); h.find(node => node.type?.name === 'SettingsConfirmation').props.close(); h.render(); assert.equal(h.commands.length, 1);
  open(); h.render(); const confirm = h.find(node => node.type?.name === 'SettingsConfirmation').props.accept; confirm(); confirm(); h.render();
  assert.equal(h.commands.length, 2);
  assert.deepEqual({ ...h.commands[1], requestId: 'request' }, { command: 'resetSettings', requestId: 'request', workspace: '/workspace', revision: 'one', confirmed: true });
}));
test('workspace switch rejects prior results and fetches the current configuration', () => withHarness({}, h => {
  const oldRequest = h.commands[0].requestId;
  h.render({ workspace: '/workspace/new' }); assert.equal(h.commands.length, 2); assert.equal(h.commands.at(-1).workspace, '/workspace/new');
  h.render({ result: { type: 'settings:result', requestId: oldRequest, workspace: '/workspace', ok: true, settings } });
  assert.equal(h.field('search.max_results'), undefined);
  h.respond({ settings: { ...settings, path: '/workspace/new/.tapl/config.toml' } }); assert.ok(h.field('search.max_results'));
}));
test('unsupported runtime offers retry without separate local preferences', () => withHarness({}, h => {
  h.respond({ ok: false, settings: undefined, code: 'unsupported_settings', message: 'Older server' });
  assert.equal(h.find(node => node.props?.id === 'settings-language'), undefined); assert.equal(h.field('viewer.language'), undefined);
  h.find(node => node.type === 'button' && node.props.children === 'Retry loading').props.onClick(); h.render(); assert.equal(h.commands.at(-1).command, 'getSettings');
}));
test('duplicate model rows remain visible and never collapse into saved dictionary', () => {
  let invalid, change;
  // Resolve the actual nested editor with the same instrumented React instance.
  withHarness({ value: settings.values['subagents.models'], onChange: value => { change = value; }, onInvalid: value => { invalid = value; } }, h => {
    const inputs = () => h.nodes().filter(node => node.type === 'input');
    inputs()[1].props.onChange({ currentTarget: { value: 'model.with.dots' } }); h.render();
    assert.equal(invalid, true); assert.equal(change, undefined); assert.equal(inputs().length, 2);
    inputs()[1].props.onChange({ currentTarget: { value: 'custom.model.v3' } }); h.render();
    assert.equal(invalid, false); assert.deepEqual(change, { 'model.with.dots': ['high'], 'custom.model.v3': ['low'] });
  }, api => api.ModelsEditor);
});
test('settings remains selected through background RUN updates and retains Back', () => {
  const { model } = load();
  const initial = { type: 'overview', status: { active_run: null, task_counts: {}, plans: [], tasks: [], findings: [] }, archives: [], searchQuery: '' };
  const state = model.navigate(model.createNavigation(initial), { page: 'settings', runKey: '' }, true);
  const next = model.receiveView(state, { type: 'run', snapshot: { run: { id: 'new-run' } } });
  assert.equal(next.route.page, 'settings'); assert.deepEqual(next.trail, state.trail); assert.equal(model.back(next).route.page, 'current');
});
test('registry Viewer controls localize options and use a single executable path input', () => {
  const { SettingEditor, I18nProvider } = load();
  for (const locale of ['en', 'ko']) {
    const editor = field => renderToStaticMarkup(React.createElement(I18nProvider, { locale }, React.createElement(SettingEditor, { field, id: field.key, value: 'auto', onChange() {}, onInvalid() {} })));
    const language = editor(fields[5]); assert.match(language, /한국어/); assert.match(language, /English/); assert.match(language, locale === 'ko' ? /자동/ : /Automatic/);
    const layout = editor(fields[6]); assert.match(layout, locale === 'ko' ? /작게/ : /Small/);
    assert.match(editor(fields[7]), /type="text"/); assert.doesNotMatch(editor(fields[7]), /textarea/);
  }
});

test('App applies saved/reset metadata immediately, ignores device overrides and preserves the settings route', () => {
  const vm = require('node:vm');
  const appOutput = buildSync({ entryPoints: [path.resolve(__dirname, '../src/webview/App.tsx')],
    loader: { '.css': 'empty' }, bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
    external: ['react', 'react-dom'] }).outputFiles[0].text;
  const slots = []; let cursor = 0, dirty = false, effects = [], tree, listener;
  let state = { workspace: '/workspace', locale: 'en', userLocale: 'en', layout: 'large',
    view: { type: 'overview', status: { active_run: null }, archives: [], searchQuery: '' },
    workbench: { version: 1, theme: 'dark', route: { page: 'settings' } }, workbenchWorkspace: '/workspace' };
  const api = { getState: () => state, setState: value => { state = value; }, postMessage() {} };
  const react = { ...React,
    useRef: value => { const i = cursor++; return slots[i] ??= { current: value }; },
    useState: initial => { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], value => { const next = typeof value === 'function' ? value(slots[i]) : value;
        if (!Object.is(next, slots[i])) { slots[i] = next; dirty = true; } }]; },
    useEffect: (effect, deps) => { const i = cursor++, previous = slots[i];
      if (previous && deps?.every((value, n) => Object.is(value, previous.deps?.[n]))) return;
      effects.push(() => { previous?.cleanup?.(); slots[i] = { deps, cleanup: effect() }; }); }
  };
  const context = vm.createContext({ module: { exports: {} }, require: name => name === 'react' ? react : require(name),
    navigator: { language: 'ko-KR' }, document: { documentElement: { lang: 'en' } },
    window: { addEventListener: (name, callback) => { if (name === 'message') listener = callback; }, removeEventListener() {} },
    acquireVsCodeApi: () => api });
  vm.runInContext(appOutput, context);
  const render = () => { let passes = 0; do { dirty = false; cursor = 0; effects = []; tree = context.module.exports.App();
    for (const effect of effects) effect(); assert.ok(++passes < 10); } while (dirty); };
  const workbench = () => nodes(tree).find(node => node.type?.name === 'Workbench').props;
  const receive = message => { listener({ data: message }); render(); };
  try {
    render(); assert.equal(tree.props.locale, 'ko'); assert.equal(workbench().layout, 'auto');
    const seed = workbench().initialState, originalView = workbench().view;
    receive({ type: 'view:update', workspace: '/workspace', view: originalView, locale: 'en', layout: 'small',
      preferences: { language: 'auto', layout: 'small', mcp_path: '' } });
    assert.equal(tree.props.locale, 'en'); assert.equal(workbench().layout, 'small');
    receive({ type: 'settings:result', requestId: 'failed', workspace: '/workspace', ok: false, locale: 'ko', layout: 'large' });
    assert.equal(tree.props.locale, 'en'); assert.equal(workbench().layout, 'small');
    receive({ type: 'settings:result', requestId: 'save', workspace: '/workspace', ok: true, action: 'save', settings,
      locale: 'ko', layout: 'large', preferences: { language: 'ko', layout: 'large', mcp_path: '' } });
    assert.equal(tree.props.locale, 'ko'); assert.equal(workbench().layout, 'large');
    assert.equal(workbench().view, originalView); assert.equal(workbench().initialState, seed);
    assert.equal(workbench().settingsResult.requestId, 'save');
    receive({ type: 'settings:result', requestId: 'old-workspace', workspace: '/other', ok: true, locale: 'en', layout: 'small' });
    assert.equal(tree.props.locale, 'ko'); assert.equal(workbench().layout, 'large');
    receive({ type: 'settings:result', requestId: 'reset', workspace: '/workspace', ok: true, action: 'reset',
      settings: { ...settings, values: { ...settings.values, 'viewer.language': 'auto', 'viewer.layout': 'auto' } } });
    assert.equal(tree.props.locale, 'ko'); assert.equal(workbench().layout, 'auto');
    assert.equal(workbench().view, originalView); assert.equal(workbench().initialState, seed);
  } finally { for (const slot of slots) slot?.cleanup?.(); }
});

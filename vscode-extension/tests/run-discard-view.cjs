const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const filename = path.join(__dirname, 'run-discard-render.cjs');
const output = buildSync({
  stdin: { contents: "export { RunTabs } from './src/webview/App';", resolveDir: path.resolve(__dirname, '..') },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react-dom']
}).outputFiles[0].text;
const runA = { id: 'run-a', session_id: 'owner-a', request_summary: 'Selected RUN' };
const runB = { id: 'run-b', session_id: 'owner-b', request_summary: 'Unselected RUN' };
function load(react = React) {
  const compiled = new Module(filename, module);
  compiled.filename = filename; compiled.paths = module.paths;
  compiled.require = (name) => name === 'react' ? react : module.require(name);
  compiled._compile(output, filename);
  return compiled.exports.RunTabs;
}
// Exercise actual component handlers and effects without a new DOM dependency.
// Native focus containment and layout remain browser integration checks.
function harness(overrides = {}) {
  const slots = []; let cursor = 0; let dirty = false; let effects = []; let tree;
  const commands = [];
  const props = { runs: [runA, runB], selectedId: 'run-a', workspace: '/workspace/a', discardSupported: true, send: (value) => commands.push(value), ...overrides };
  class Element {
    isConnected = true; open = false;
    focus() { global.document.activeElement = this; }
    showModal() { this.open = true; }
    close() { this.open = false; }
    querySelector() { return null; }
  }
  const opener = new Element(); global.HTMLElement = Element; global.document = { activeElement: opener };
  const react = { ...React,
    useContext: (context) => context._currentValue,
    useRef: (value) => { const index = cursor++; return slots[index] ??= { current: value }; },
    useState: (initial) => {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], (value) => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; dirty = true; }];
    },
    useEffect: (effect, deps) => {
      const index = cursor++; const previous = slots[index];
      if (previous && deps?.every((value, i) => Object.is(value, previous.deps?.[i]))) return;
      effects.push(() => { previous?.cleanup?.(); slots[index] = { deps, cleanup: effect() }; });
    }
  };
  const Component = load(react);
  function nodes(node) {
    if (arguments.length === 0) node = tree;
    if (!node || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(nodes);
    return [node, ...nodes(node.props?.children)];
  }
  function render(update = {}) {
    Object.assign(props, update); let passes = 0;
    do {
      dirty = false; cursor = 0; effects = []; tree = Component(props);
      for (const node of nodes()) if (node.ref && !node.ref.current) node.ref.current = new Element();
      for (const effect of effects) effect();
      assert.ok(++passes < 10, 'effects settle');
    } while (dirty);
  }
  const find = (predicate) => nodes().find(predicate);
  const close = (id = 'run-b') => nodes(find((node) => node.type === 'div' && node.key === id)).find((node) => node.props?.className === 'tapl-run-tab-close');
  render();
  return { render, find, close, commands, opener, props, nodes, cleanup() { for (const slot of slots) slot?.cleanup?.(); delete global.document; delete global.HTMLElement; } };
}
function withHarness(overrides, action) { const h = harness(overrides); try { action(h); } finally { h.cleanup(); } }
const dialog = (h) => h.find((node) => node.type === 'dialog');
const confirm = (h) => h.find((node) => node.props?.className === 'btn btn-error btn-sm');
const cancel = (h) => h.find((node) => node.props?.className === 'btn btn-secondary btn-sm');
const confirmationInput = (h) => h.find((node) => node.props?.id === 'tapl-discard-confirmation-id');
function enterRunId(h, value = 'run-b') {
  confirmationInput(h).props.onChange({ currentTarget: { value } });
  h.render();
}

test('close icons are capability-gated siblings with accessible labels and tooltips', () => {
  const Component = load();
  const props = { runs: [runA], selectedId: runA.id, workspace: '/work', discardSupported: true, send() {} };
  const html = renderToStaticMarkup(React.createElement(Component, props));
  assert.match(html, /<\/button><button class="tapl-run-tab-close"[^>]*aria-label="Close RUN: Selected RUN"[^>]*title="Close RUN: Selected RUN"/);
  assert.doesNotMatch(renderToStaticMarkup(React.createElement(Component, { ...props, discardSupported: false })), /tapl-run-tab-close/);
  assert.doesNotMatch(renderToStaticMarkup(React.createElement(Component, { ...props, workspace: undefined })), /tapl-run-tab-close/);
  assert.doesNotMatch(renderToStaticMarkup(React.createElement(Component, { ...props, runs: [{ ...runA, id: undefined }] })), /tapl-run-tab-close/);
  assert.doesNotMatch(renderToStaticMarkup(React.createElement(Component, { ...props, runs: [{ ...runA, session_id: undefined }] })), /tapl-run-tab-close/);
});

test('opening and cancelling or pressing Escape never sends a discard', () => withHarness({}, (h) => {
  h.close().props.onClick(); h.render();
  assert.ok(dialog(h).ref.current.open);
  assert.equal(confirmationInput(h).props.value, '');
  assert.equal(global.document.activeElement, cancel(h).ref.current, 'Cancel gets default focus');
  assert.equal(h.commands.length, 0);
  cancel(h).props.onClick(); h.render();
  assert.equal(dialog(h), undefined);
  assert.equal(global.document.activeElement, h.opener, 'focus returns to opener');
  h.close().props.onClick(); h.render();
  let prevented = false;
  dialog(h).props.onCancel({ preventDefault() { prevented = true; } }); h.render();
  assert.ok(prevented); assert.equal(dialog(h), undefined); assert.deepEqual(h.commands, []);
}));

test('Tab and Shift+Tab keep focus within the confirmation dialog', () => withHarness({}, (h) => {
  h.close().props.onClick(); h.render();
  const control = () => ({ getClientRects() { return [{}]; }, focus() { global.document.activeElement = this; } });
  const first = control(), last = control();
  const element = dialog(h).ref.current;
  element.querySelectorAll = () => [first, last];
  for (const [start, shiftKey, expected] of [[last, false, first], [first, true, last]]) {
    global.document.activeElement = start;
    let prevented = false;
    dialog(h).props.onKeyDown({ key: 'Tab', shiftKey, currentTarget: element, preventDefault() { prevented = true; } });
    assert.ok(prevented);
    assert.equal(global.document.activeElement, expected);
  }
  assert.deepEqual(h.commands, []);
}));

test('confirmation targets the clicked unselected RUN exactly once with captured identity', () => withHarness({}, (h) => {
  h.close().props.onClick(); h.render();
  h.render({ runs: [runA, { ...runB, request_summary: 'Changed by polling' }] });
  assert.ok(h.nodes(dialog(h)).some((node) => node.props?.children === 'Unselected RUN'));
  enterRunId(h);
  const submit = confirm(h).props.onClick; submit(); submit(); h.render();
  assert.deepEqual(h.commands, [{ command: 'discardRun', runId: 'run-b', targetSessionId: 'owner-b', workspace: '/workspace/a', confirmed: true, confirmationRunId: 'run-b' }]);
  assert.equal(confirm(h).props.disabled, true); assert.equal(cancel(h).props.disabled, true);
  h.render({ discardResult: { runId: 'run-b', ok: true }, runs: [runA] });
  assert.equal(dialog(h), undefined); assert.equal(h.props.selectedId, 'run-a');
}));

test('host failure stays inline and allows a deliberate retry', () => withHarness({}, (h) => {
  h.close().props.onClick(); h.render(); enterRunId(h); confirm(h).props.onClick(); h.render();
  h.render({ discardResult: { runId: 'another-run', ok: false, message: 'Unrelated' } });
  assert.equal(confirm(h).props.disabled, true);
  h.render({ discardResult: { runId: 'run-b', ok: false, message: 'Database locked' } });
  assert.equal(h.find((node) => node.props?.role === 'alert').props.children, 'Database locked');
  assert.equal(confirm(h).props.disabled, false);
  assert.equal(confirmationInput(h).props.value, 'run-b', 'a failed attempt retains the entered proof for deliberate retry');
  confirm(h).props.onClick(); h.render(); assert.equal(h.commands.length, 2);
  h.render({ discardResult: { runId: 'run-b', ok: true } }); assert.equal(dialog(h), undefined);
}));

test('workspace changes, disappearing RUNs and changed owners invalidate confirmation', () => {
  for (const update of [{ workspace: '/workspace/b' }, { runs: [runA] }, { runs: [runA, { ...runB, session_id: 'new-owner' }] }]) {
    withHarness({}, (h) => { h.close().props.onClick(); h.render(); h.render(update); assert.equal(dialog(h), undefined); assert.deepEqual(h.commands, []); });
  }
});

test('an old result cannot resolve a newly opened dialog and legacy owners stay explicit', () => withHarness({
  runs: [runA, { ...runB, session_id: '' }], discardResult: { runId: 'run-b', ok: true }
}, (h) => {
  h.close().props.onClick(); h.render();
  assert.ok(dialog(h), 'old successful result does not dismiss a new confirmation');
  enterRunId(h);
  confirm(h).props.onClick(); h.render();
  assert.equal(h.commands[0].targetSessionId, '');
  assert.equal(confirm(h).props.disabled, true);
  h.render({ discardResult: { runId: 'run-b', ok: false } });
  assert.match(h.find((node) => node.props?.role === 'alert').props.children, /Could not discard/);
}));

test('missing, shortened, case-changed and whitespace-padded proof cannot send a discard', () => withHarness({}, (h) => {
  h.close().props.onClick(); h.render();
  const input = confirmationInput(h);
  assert.equal(input.props.value, '');
  assert.equal(input.props.autoComplete, 'off');
  assert.equal(input.props.autoCorrect, 'off');
  assert.equal(input.props.autoCapitalize, 'none');
  assert.equal(input.props.spellCheck, false);
  assert.ok(h.find((node) => node.type === 'label' && node.props.htmlFor === input.props.id));
  for (const value of ['', 'run-', 'RUN-B', ' run-b', 'run-b ', 'run-b\n', 'run-a']) {
    enterRunId(h, value);
    assert.equal(confirm(h).props.disabled, true, `reject ${JSON.stringify(value)}`);
    confirm(h).props.onClick(); h.render();
    assert.equal(confirmationInput(h).props['aria-invalid'], value.length > 0);
    if (value) assert.match(h.find((node) => node.props?.role === 'status').props.children, /does not match exactly/);
  }
  assert.deepEqual(h.commands, []);
}));

test('typing or pasting the full hash enables confirmation and sends the actual entered value', () => {
  const fullId = 'Ab12Cd34-5678-90ef-aBCd-1234567890aB';
  for (const mode of ['type', 'paste']) withHarness({ runs: [runA, { ...runB, id: fullId }] }, (h) => {
    h.close(fullId).props.onClick(); h.render();
    assert.ok(h.nodes(dialog(h)).some((node) => node.type === 'code' && node.props.children === fullId), 'full hash is visible and selectable');
    if (mode === 'type') for (let length = 1; length < fullId.length; length++) {
      enterRunId(h, fullId.slice(0, length));
      assert.equal(confirm(h).props.disabled, true);
    }
    enterRunId(h, fullId);
    assert.equal(confirm(h).props.disabled, false);
    const actualEntry = confirmationInput(h).props.value;
    confirm(h).props.onClick(); h.render();
    assert.equal(h.commands[0].confirmationRunId, actualEntry);
    assert.equal(h.commands[0].runId, fullId);
    assert.equal(confirmationInput(h).props.disabled, true);
  });
});

test('Cancel, Escape and opening another RUN clear the entered confirmation', () => withHarness({}, (h) => {
  h.close().props.onClick(); h.render(); enterRunId(h);
  cancel(h).props.onClick(); h.render();
  h.close().props.onClick(); h.render();
  assert.equal(confirmationInput(h).props.value, '');
  enterRunId(h);
  dialog(h).props.onCancel({ preventDefault() {} }); h.render();
  h.close('run-a').props.onClick(); h.render();
  assert.equal(confirmationInput(h).props.value, '');
  assert.equal(confirm(h).props.disabled, true);
  enterRunId(h, 'run-b');
  confirm(h).props.onClick(); h.render();
  assert.deepEqual(h.commands, []);
}));

test('arrow, Home and End handlers preserve owner-based selection', () => withHarness({}, (h) => {
  const tab = h.find((node) => node.props?.id === 'tapl-run-tab-run-b');
  const list = h.find((node) => node.props?.role === 'tablist');
  list.ref.current.querySelectorAll = () => [{ focus() {} }, { focus() {} }];
  for (const key of ['Home', 'ArrowRight', 'End']) tab.props.onKeyDown({ key, preventDefault() {} });
  assert.deepEqual(h.commands, [{ command: 'selectRun', sessionId: 'owner-b' }]);
}));

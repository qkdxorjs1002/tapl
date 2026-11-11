const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const filename = path.join(__dirname, 'run-overview-render.cjs');
const output = buildSync({
  stdin: {
    contents: "export { CurrentRun, TaskStatus } from './src/webview/workbench/RunViews'; export { I18nProvider } from './src/webview/i18n'; export { translate } from './src/i18n'; export { useMindmapViewport } from './src/webview/workbench/mindmapViewport';",
    resolveDir: path.resolve(__dirname, '..')
  },
  loader: { '.css': 'empty' }, bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react-dom']
}).outputFiles[0].text;
function load(react = React) {
  const compiled = new Module(filename, module);
  compiled.filename = filename;
  compiled.paths = module.paths;
  compiled.require = (name) => name === 'react' ? react : module.require(name);
  compiled._compile(output, filename);
  return compiled.exports;
}
const { CurrentRun, TaskStatus, I18nProvider, translate } = load();
const run = {
  request_summary: 'Actual recorded request', id: 'same-run', source_db: '/actual/peer.sqlite3', slug: 'Actual RUN', status: 'active',
  work_type: 'implementation', workflow_mode: 'planned', record_mode: 'full'
};
const task = (id, status = 'In Progress', extra = {}) => ({
  id, stable_id: `TASK-${String(id).padStart(3, '0')}`, kind: 'task', title: `Actual task ${id}`,
  status, run_id: run.id, source_db: run.source_db, ...extra
});
const plan = (id, extra = {}) => ({
  id, stable_id: `PLAN-${String(id).padStart(3, '0')}`, kind: 'plan', title: `Actual plan ${id}`,
  status: 'Finalized', run_id: run.id, source_db: run.source_db, ...extra
});
const snapshot = (extra = {}) => ({
  run, plans: [], tasks: [], findings: [], task_counts: {}, active_batches: [], active_executions: [],
  readonly: false, ...extra
});
function render(value, locale = 'en', Component = CurrentRun, extra = {}) {
  return renderToStaticMarkup(React.createElement(I18nProvider, { locale }, React.createElement(Component, {
    snapshot: value, title: 'Actual RUN', open() {}, ...extra
  })));
}
const occurrences = (html, text) => html.split(text).length - 1;

test('Current RUN renders the actual mindmap and all TASK statuses in both languages', () => {
  const states = ['Pending', 'In Progress', 'Blocked', 'Completed', 'Skipped', 'Custom status', undefined];
  const tasks = states.map((state, index) => task(index + 1, state, { status: state, spec_id: 'PLAN-001' }));
  for (const locale of ['en', 'ko']) {
    const html = render(snapshot({ plans: [plan(1)], tasks }), locale);
    assert.match(html, /class="wb-mindmap wb-run-mindmap"/);
    assert.equal(occurrences(html, 'data-kind="run"'), 1);
    assert.equal(occurrences(html, 'data-kind="plan"'), 1);
    assert.equal(occurrences(html, 'data-kind="task"'), 7);
    assert.equal(occurrences(html, 'class="wb-mm-edge"'), 8);
    for (const item of tasks) assert.ok(html.includes(item.title), String(item.status));
    assert.ok(html.includes('Actual recorded request'));
    assert.ok(html.includes('Actual plan 1'));
    assert.ok(html.includes(`aria-label="${translate(locale, 'wbMindmap')}"`));
    for (const key of ['wbCompleted', 'wbMindmapZoomOut', 'wbMindmapZoomIn', 'wbMindmapFit']) assert.ok(html.includes(translate(locale, key)), key);
    for (const key of ['pending', 'inProgress', 'blocked', 'completed', 'skipped']) assert.ok(html.includes(translate(locale, key)), key);
    assert.match(html, /wb-mm-percent">14<small>%/);
    assert.match(html, /wb-mm-plan-track/);
    assert.doesNotMatch(html, /wb-run-information|wb-current-overview|wb-active-section|wb-active-task|wb-plan-section|wb-plan-summary|wb-overview-fields|wb-overview-facts|data-wb-track|<h1/);
    assert.ok(!html.includes(translate(locale, 'wbActiveTasks')));
  }
});

test('empty RUN has one real root and missing RUN retains its localized guidance', () => {
  for (const locale of ['en', 'ko']) {
    const html = render(snapshot(), locale);
    assert.equal(occurrences(html, 'data-kind="run"'), 1);
    assert.equal(occurrences(html, 'data-kind="task"'), 0);
    assert.equal(occurrences(html, 'data-kind="plan"'), 0);
    assert.match(html, /wb-mm-percent">0<small>%/);
    assert.ok(!html.includes(translate(locale, 'wbNoPlans')));
    assert.ok(!html.includes(translate(locale, 'wbNoActiveTasks')));
    const missing = render(undefined, locale);
    assert.ok(missing.includes(translate(locale, 'wbNoRun')));
    assert.ok(missing.includes(translate(locale, 'wbNoRunHelp')));
    assert.doesNotMatch(missing, /wb-run-mindmap/);
  }
});

test('nodes stay compact, escape recorded titles, and exclude other sources and RUNs', () => {
  const html = render(snapshot({ plans: [plan(1, { summary: 'Hidden plan narrative', selected_approach: 'Hidden approach' })], tasks: [
    task(1, 'Blocked', { title: 'Actual <script>title</script>', spec_id: 'PLAN-001', goal: 'Hidden goal', custom_fields: { owner: 'Hidden owner' } }),
    task(2, 'Completed', { source_db: '/other/source.sqlite3', title: 'Foreign source item' }),
    task(3, 'Completed', { run_id: 'other-run', title: 'Foreign RUN item' })
  ] }));
  assert.match(html, /Actual &lt;script&gt;title&lt;\/script&gt;/);
  assert.doesNotMatch(html, /Hidden plan narrative|Hidden approach|Hidden goal|Hidden owner|Foreign source item|Foreign RUN item|<script>/);
  assert.equal(occurrences(html, 'data-kind="task"'), 1);
  assert.match(html, /wb-mm-percent">0<small>%/);
});

function interactionTree(Component, props) {
  const react = {
    ...React,
    useContext: (context) => context._currentValue,
    useState: (initial) => [typeof initial === 'function' ? initial() : initial, () => {}],
    useRef: (current) => ({ current }), useEffect() {}, useLayoutEffect() {}, useMemo: (factory) => factory()
  };
  function nodes(node) {
    if (!node || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(nodes);
    return [node, ...(typeof node.type === 'function' ? nodes(node.type(node.props)) : nodes(node.props?.children))];
  }
  return nodes(load(react)[Component](props));
}

test('shared viewport accepts structural DAGs and calculates every valid edge without RUN topology', () => {
  const react = {
    ...React,
    useRef: (current) => ({ current }),
    useEffect() {},
    useMemo: (factory) => factory()
  };
  const { useMindmapViewport } = load(react);
  const graph = {
    nodes: [
      { key: 'source', x: -200, y: 0, width: 100, height: 60 },
      { key: 'memory-a', x: 0, y: -80, width: 100, height: 60 },
      { key: 'memory-b', x: 0, y: 80, width: 100, height: 60 },
      { key: 'cue', x: 200, y: 0, width: 100, height: 60 }
    ],
    edges: [
      { from: 'source', to: 'memory-a' }, { from: 'source', to: 'memory-b' },
      { from: 'memory-a', to: 'cue' }, { from: 'memory-b', to: 'cue' },
      { from: 'missing', to: 'cue' }
    ],
    bounds: { minX: -250, minY: -110, maxX: 250, maxY: 110 }
  };
  const viewport = useMindmapViewport({ graph, cameraKey: 'memory:source', setActive() {} });
  assert.equal(viewport.hostRef.current, null);
  assert.equal(viewport.worldRef.current, null);
  assert.equal(viewport.controlsRef.current, undefined);
  assert.deepEqual(viewport.edges.map(({ from, to, index }) => ({ from, to, index })), graph.edges.slice(0, 4).map((edge, index) => ({ ...edge, index })));
  assert.deepEqual(viewport.edges[0], {
    from: 'source', to: 'memory-a', index: 0,
    start: { x: -150, y: 0 }, end: { x: -50, y: -80 }, middle: -100,
    path: 'M -150 0 C -100 0, -100 -80, -50 -80'
  });
  assert.equal(viewport.edges.filter((edge) => edge.to === 'cue').length, 2);
  viewport.suppressClickCapture({
    preventDefault() { assert.fail('stationary click must remain available'); },
    stopPropagation() { assert.fail('stationary click must propagate'); }
  });
});

test('single-click nodes pass the original item and exact source RUN; invalid record IDs are guarded', () => {
  const selectedTask = task(12);
  const selectedPlan = plan(3);
  const calls = [];
  const invalidIds = [undefined, '12', NaN, Infinity];
  const value = snapshot({
    tasks: [selectedTask, ...invalidIds.map((id, i) => task(id, 'In Progress', { stable_id: `TASK-invalid-${i}` }))],
    plans: [selectedPlan, ...invalidIds.map((id, i) => plan(id, { stable_id: `PLAN-invalid-${i}` }))]
  });
  let backed = 0;
  const nodes = interactionTree('CurrentRun', { snapshot: value, title: 'Actual RUN', open: (...args) => calls.push(args), back: () => backed++ });
  const cards = nodes.filter((node) => node.type === 'button' && node.props.className === 'wb-mm-node-button');
  assert.equal(cards.length, 10);
  for (const card of cards) card.props.onClick();
  assert.equal(calls.length, 2);
  assert.ok(calls.some(([actual]) => actual === selectedPlan));
  assert.ok(calls.some(([actual]) => actual === selectedTask));
  for (const [, actualRun] of calls) assert.strictEqual(actualRun, run);
  assert.equal(cards.filter((card) => card.props.disabled).length, 8);
  assert.ok(cards.filter((card) => card.props.disabled).every((card) => card.props.title === translate('en', 'wbRecordUnavailable')));
  nodes.find((node) => node.props?.['data-wb-focus'] === 'back').props.onClick();
  assert.equal(backed, 1);
  assert.equal(nodes.filter((node) => node.props?.onDoubleClick).length, 0);
});

test('standalone TASK status retains every status, filtering, search and exact record navigation', () => {
  const statuses = ['Pending', 'In Progress', 'Blocked', 'Completed', 'Skipped', 'Custom status', undefined];
  const tasks = statuses.map((status, index) => task(index + 1, status, { status }));
  const value = snapshot({ tasks });
  const prefs = { taskFilter: 'all', taskQuery: '' };
  for (const locale of ['en', 'ko']) {
    const html = render(value, locale, TaskStatus, { prefs, update() {} });
    for (const item of tasks) assert.ok(html.includes(item.title), String(item.status));
    assert.match(html, /class="table wb-tasks-table"/);
    assert.ok(html.includes(translate(locale, 'wbTaskSearch')));
    assert.doesNotMatch(html, /wb-active-section/);
  }
  const filtered = render(value, 'en', TaskStatus, { prefs: { ...prefs, taskFilter: 'Blocked' }, update() {} });
  assert.ok(filtered.includes('Actual task 3'));
  assert.ok(!filtered.includes('Actual task 2'));
  const changes = []; const calls = [];
  const nodes = interactionTree('TaskStatus', { snapshot: value, prefs, update: (change) => changes.push(change), open: (...args) => calls.push(args) });
  nodes.find((node) => node.props?.['data-wb-focus'] === 'filter:Completed').props.onClick();
  nodes.find((node) => node.props?.['data-wb-focus'] === 'task-query').props.onChange({ target: { value: 'Actual task 3' } });
  nodes.find((node) => node.props?.['data-wb-focus'] === 'task:3').props.onClick();
  assert.deepEqual(changes, [{ taskFilter: 'Completed' }, { taskQuery: 'Actual task 3' }]);
  assert.strictEqual(calls[0][0], tasks[2]);
  assert.strictEqual(calls[0][1], run);
});

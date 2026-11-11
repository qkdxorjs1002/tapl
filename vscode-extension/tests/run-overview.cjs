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
    contents: "export { CurrentRun, TaskStatus } from './src/webview/workbench/RunViews'; export { I18nProvider } from './src/webview/i18n'; export { translate } from './src/i18n';",
    resolveDir: path.resolve(__dirname, '..')
  },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react-dom']
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
  id: 'same-run', source_db: '/actual/peer.sqlite3', slug: 'Actual RUN', status: 'active',
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

test('Current RUN shows PLAN before exact In Progress tasks and preserves compact RUN information', () => {
  const inactive = ['Pending', 'Blocked', 'Completed', 'Skipped', 'Custom status', undefined, 'In Progress ', 'in progress'];
  const tasks = [task(10), task(2), ...inactive.map((status, index) => task(index + 20, status, { status }))];
  for (const locale of ['en', 'ko']) {
    const html = render(snapshot({ tasks, plans: [plan(1)] }), locale);
    assert.equal(occurrences(html, 'class="card wb-active-task"'), 2);
    assert.ok(html.indexOf('TASK-002') < html.indexOf('TASK-010'), 'stable IDs sort numerically');
    for (const item of tasks.slice(2)) assert.ok(!html.includes(item.title), item.status);
    assert.ok(html.indexOf('wb-run-information') < html.indexOf('wb-active-section'));
    assert.ok(html.indexOf('wb-plan-section') < html.indexOf('wb-active-section'));
    assert.ok(html.includes('data-wb-track="active-tasks"'));
    assert.ok(html.includes(translate(locale, 'wbActiveTasks')));
    for (const key of ['wbMetadataImplementation', 'wbMetadataPlanned', 'wbMetadataFull']) {
      assert.ok(html.includes(translate(locale, key)));
    }
    assert.equal(occurrences(html, '<h1 '), 1);
    assert.doesNotMatch(html, /wb-flow|wb-blocker|data-wb-track="flow"/);
  }
});

test('no-active state stays explicit for empty tasks and RUNs with only other statuses', () => {
  for (const tasks of [[], [task(1, 'Blocked'), task(2, 'Completed'), task(3, 'Pending')]]) {
    for (const locale of ['en', 'ko']) {
      const html = render(snapshot({ tasks, plans: [plan(1)] }), locale);
      assert.ok(html.includes(`<p class="wb-active-empty">${translate(locale, 'wbNoActiveTasks')}</p>`));
      assert.ok(html.includes('Actual plan 1'));
      assert.doesNotMatch(html, /class="card wb-active-task"|wb-flow|wb-blocker/);
      assert.ok(!html.includes(translate(locale, 'wbNoTasksHelp')), 'no unrelated instructional text');
    }
  }
  assert.ok(render(undefined).includes(translate('en', 'wbNoRun')));
  const missingMetadata = render(snapshot({ run: { id: run.id } }));
  assert.doesNotMatch(missingMetadata, /wb-run-information/);
});

test('typed task narratives and actual metadata are readable, localized, escaped and not replaced by body summaries', () => {
  const item = task(3, 'In Progress', {
    goal: 'Recorded goal <script>unsafe()</script>', action: 'First action\nSecond action', verification: 'Recorded verification',
    body: 'Duplicate body should not appear', spec_id: 'PLAN-007', depends_on: ['TASK-001', 'TASK-002'],
    custom_fields: { owner: 'Actual owner', goal: 'Legacy goal should not override the typed field' },
    executor_kind: 'main', execution_mode: 'sequential',
    active_execution: { execution_id: 'actual-execution', executor_ref: 'Actual executor', executor_kind: 'subagent', execution_mode: 'parallel' },
    execution_timing: { started_at: '2026-11-11T00:00:00Z', finished_at: null, elapsed_seconds: 0, running_since: null, as_of: '2026-11-11T00:00:00Z' }
  });
  for (const locale of ['en', 'ko']) {
    const html = render(snapshot({ tasks: [item] }), locale);
    for (const text of ['Recorded goal &lt;script&gt;unsafe()&lt;/script&gt;', 'First action\nSecond action', 'Recorded verification', 'Actual owner', 'Actual executor', 'PLAN-007']) {
      assert.ok(html.includes(text), text);
    }
    for (const key of ['goal', 'action', 'verification', 'wbOwner', 'wbExecutionRef', 'executor', 'executionMode', 'wbParentPlan', 'dependencies', 'elapsedTime', 'wbSubagent', 'wbParallel']) {
      assert.ok(html.includes(translate(locale, key)), key);
    }
    assert.ok(html.includes(translate(locale, 'wbItems', { count: 2 })));
    assert.ok(html.includes(locale === 'ko' ? '0초' : '0s'), 'zero is measured');
    assert.doesNotMatch(html, /<script>|Duplicate body should|Legacy goal should|TASK-001|TASK-002|>main<|>sequential</);
    assert.ok(!html.includes(translate(locale, 'notMeasured')));
  }
});

test('sparse tasks omit invented properties, and old body or custom goal values remain useful fallbacks', () => {
  const sparse = render(snapshot({ tasks: [task(1)] }));
  assert.doesNotMatch(sparse, /wb-overview-fields|wb-overview-facts/);
  for (const key of ['wbOwner', 'wbParentPlan', 'dependencies', 'notMeasured']) assert.ok(!sparse.includes(translate('en', key)));
  const fallback = render(snapshot({ tasks: [
    task(1, 'In Progress', { body: '## Original heading\n\nActual **body** summary', execution_mode: 'sequential', executor_kind: 'main' }),
    task(2, 'In Progress', { custom_fields: { goal: 'Actual legacy goal', owner: false, assignee: 'Actual assignee' } })
  ] }));
  assert.match(fallback, /Actual body summary/);
  assert.match(fallback, /Actual legacy goal/);
  assert.match(fallback, /Actual assignee/);
  assert.doesNotMatch(fallback, /Original heading|>main<|>sequential<|Not measured/);
});

test('rich and sparse PLAN cards preserve the horizontal track and deduplicate repeated summaries', () => {
  const value = snapshot({ plans: [
    plan(1, { summary: 'A shared plan purpose', objective: ' A shared\nplan purpose ', selected_approach: 'Actual selected approach', validation: 'Actual validation', body: 'A shared plan purpose' }),
    plan(2, { objective: 'Actual objective', goal: 'Actual plan goal' }),
    plan(3),
    plan(4, { body: '## Imported heading\n\nActual imported plan summary' })
  ] });
  for (const locale of ['en', 'ko']) {
    const html = render(value, locale);
    assert.equal(occurrences(html, 'class="card wb-plan-summary"'), 4);
    assert.match(html, /data-wb-track="plans" role="region" aria-label="PLAN" tabindex="0"/);
    assert.doesNotMatch(html, /wb-single-plan/);
    assert.equal(occurrences(html, 'A shared plan purpose'), 1);
    for (const text of ['Actual selected approach', 'Actual validation', 'Actual objective', 'Actual plan goal', 'Actual imported plan summary']) {
      assert.ok(html.includes(text), text);
    }
    for (const key of ['wbApproach', 'wbValidation', 'wbObjective', 'goal']) assert.ok(html.includes(translate(locale, key)), key);
    assert.doesNotMatch(html, /Imported heading|Verify record context/);
  }
  assert.match(render(snapshot({ plans: [plan(1)] })), /wb-single-plan/);
  assert.ok(render(snapshot()).includes(translate('en', 'wbNoPlans')));
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

test('whole-card handlers pass the original item and exact source RUN, and guard all nonnumeric IDs', () => {
  const selectedTask = task(12, 'In Progress', { source_db: '/actual/item-source.sqlite3' });
  const selectedPlan = plan(3);
  const calls = [];
  const invalidIds = [undefined, '12', NaN, Infinity];
  const value = snapshot({
    tasks: [selectedTask, ...invalidIds.map((id, i) => task(id, 'In Progress', { stable_id: `TASK-invalid-${i}` }))],
    plans: [selectedPlan, ...invalidIds.map((id, i) => plan(id, { stable_id: `PLAN-invalid-${i}` }))]
  });
  let backed = 0;
  const nodes = interactionTree('CurrentRun', { snapshot: value, title: 'Actual RUN', open: (...args) => calls.push(args), back: () => backed++ });
  const cards = nodes.filter((node) => node.type === 'button' && /wb-(active-task|plan-summary)/.test(node.props.className));
  assert.equal(cards.length, 10);
  for (const card of cards) card.props.onClick();
  assert.equal(calls.length, 2);
  assert.strictEqual(calls[0][0], selectedPlan);
  assert.strictEqual(calls[1][0], selectedTask);
  for (const [, actualRun] of calls) assert.strictEqual(actualRun, run);
  assert.equal(calls[1][0].source_db, '/actual/item-source.sqlite3');
  assert.equal(calls[1][1].source_db, '/actual/peer.sqlite3');
  assert.equal(cards.filter((card) => card.props.disabled).length, 8);
  assert.ok(cards.filter((card) => card.props.disabled).every((card) => card.props.title === translate('en', 'wbRecordUnavailable')));
  nodes.find((node) => node.props?.['data-wb-focus'] === 'back').props.onClick();
  assert.equal(backed, 1);
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

const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const filename = path.join(__dirname, 'record-detail-render.cjs');
const output = buildSync({
  stdin: { contents: "export { RecordDetail } from './src/webview/workbench/RecordDetail'; export { I18nProvider } from './src/webview/i18n'; export { translate } from './src/i18n';", resolveDir: path.resolve(__dirname, '..') },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react-dom']
}).outputFiles[0].text;
function load(react = React) {
  const compiled = new Module(filename, module);
  compiled.filename = filename; compiled.paths = module.paths;
  compiled.require = (name) => name === 'react' ? react : module.require(name);
  compiled._compile(output, filename);
  return compiled.exports;
}
const { RecordDetail, I18nProvider, translate } = load();
const run = { id: 'run-local', source_db: '/source/local.sqlite3', slug: 'Real source RUN', status: 'active' };
const base = { id: 12, stable_id: 'TASK-012', kind: 'task', title: 'Actual record title', status: 'Blocked', run_id: run.id, source_db: run.source_db };
const snapshot = (overrides = {}) => ({ run, plans: [], tasks: [], findings: [], task_counts: {}, active_batches: [], active_executions: [], readonly: false, ...overrides });
const view = (detail = {}, context) => ({ type: 'searchItem', result: { ...base, snippet: 'Search fallback', search_source: 'archive-search' }, detail: { ...base, ...detail }, context });
const escape = (text) => String(text).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#x27;');
function render(value, locale = 'en') {
  return renderToStaticMarkup(React.createElement(I18nProvider, { locale }, React.createElement(RecordDetail, { view: value, send() {} })));
}
function section(html, title) {
  return html.includes(`<h2>${title}</h2>`);
}

test('actual narrative fields become reading sections in both locales, with one hero and property rail', () => {
  const fields = { goal: 'Recorded goal', action: 'Recorded action', result: 'Recorded result', verification: '- Real verification', blocker: 'Recorded blocker', next_action: 'Recorded next action', body: 'The complete original body', source: 'manual import', run_slug: 'Run label', run_status: 'archived', archive_slug: 'saved-run', updated_at: '2026-11-10T01:02:03Z', custom_fields: { owner: 'Actual owner' } };
  for (const locale of ['en', 'ko']) {
    const html = render(view(fields), locale);
    assert.match(html, /<article class="wb-record-page">/);
    assert.match(html, /class="wb-record-context"/);
    assert.match(html, /<h1[^>]*data-wb-page-heading="true"[^>]*>Actual record title<\/h1>/);
    assert.match(html, /class="wb-record-properties"/);
    assert.equal((html.match(/<h1/g) || []).length, 1);
    for (const key of ['goal', 'action', 'result', 'verification', 'blocker', 'nextAction', 'content', 'wbProperties']) assert.ok(section(html, translate(locale, key)), key);
    for (const value of Object.values(fields).filter((value) => typeof value === 'string')) assert.ok(html.includes(escape(value.replace(/^- /, ''))), value);
    assert.match(html, /Actual owner/);
    assert.ok(html.includes(translate(locale, 'blocked')));
    assert.doesNotMatch(html, /tapl-card|tapl-topbar|Agent A|2026-11-10<\/span>/);
  }
});

test('body, raw text and snippet fallbacks stay readable without fabricated fields or relationships', () => {
  for (const [detail, expected, absent] of [
    [{ body: '# Heading\nBody **strong** and `code`\n```html\n<script>unsafe()</script>\n```', raw_text: 'Raw fallback' }, 'Body <strong>strong</strong> and <code>code</code>', 'Search fallback</p>'],
    [{ body: '', raw_text: 'Raw fallback' }, 'Raw fallback</p>', 'Search fallback</p>'],
    [{ body: '', raw_text: '' }, 'Search fallback</p>', 'Raw fallback</p>']
  ]) {
    const html = render(view(detail));
    assert.ok(html.includes(expected));
    assert.ok(!html.includes(absent));
    assert.doesNotMatch(html, /<script>|wb-related-records/);
    for (const key of ['goal', 'action', 'result', 'verification', 'blocker', 'nextAction']) assert.ok(!section(html, translate('en', key)), key);
    assert.doesNotMatch(html, /<dt>Owner<\/dt>|Waiting for prerequisite|Verify record context/);
  }
  const missing = view(); delete missing.detail;
  assert.match(render(missing), /Search fallback/);
  delete missing.result.snippet;
  assert.match(render(missing, 'ko'), new RegExp(translate('ko', 'detailUnavailable')));
  const statusFallback = render(view({ status: undefined, source: '' }));
  assert.match(statusFallback, /data-status="Blocked"/);
  assert.ok(statusFallback.includes(`<dt>Source database</dt><dd>${run.source_db}</dd>`));
});

test('all custom JSON values, extra host fields, and hostile text survive escaped and collapsed', () => {
  const html = render(view({
    body: '<img src=x onerror=alert(1)>',
    custom_fields: { zero: 0, disabled: false, absent: null, emptyArray: [], emptyObject: {}, nested: { list: [false, 0, null, '<script>'] }, '<b>label</b>': 'a long\nmultiline value' },
    future_metadata: { nested: ['future value', 0, false, null] }, archived: 0
  }));
  for (const [key,type,value] of [['zero','number','0'],['disabled','boolean','false'],['absent','null','null'],['archived','number','0']]) {
    assert.ok(html.includes(`data-value-type="${type}"><span class="wb-value-key">${key}</span><span class="wb-value-scalar">${value}</span>`));
  }
  assert.match(html, /wb-value-key">emptyArray<\/span><span class="wb-value-type">Array · 0 items/);
  assert.match(html, /wb-value-key">emptyObject<\/span><span class="wb-value-type">Object · 0 fields/);
  assert.match(html, /&lt;b&gt;label&lt;\/b&gt;/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(html, /future_metadata/);
  assert.match(html, /future value/);
  assert.match(html, /class="wb-reading-disclosure"/);
  assert.doesNotMatch(html, /<details class="wb-reading-disclosure"[^>]*\sopen(?:[\s=>])/);
  assert.doesNotMatch(html, /<img|<script|<b>label/);
});

test('task execution preserves zero, unmeasured timing, timestamps, and active executor metadata', () => {
  const timing = { started_at: '2026-11-10T00:00:00Z', finished_at: '2026-11-10T00:00:00Z', elapsed_seconds: 0, running_since: null, as_of: '2026-11-10T00:00:00Z' };
  const execution = { execution_id: 'exec-actual', execution_state: 'completed', task_id: 'TASK-012', title: 'Actual execution title', batch_id: 'batch-real', batch_state: 'completed', execution_mode: 'parallel', executor_kind: 'subagent', parallel_group: 'group-real', owned_paths: ['actual/path.ts'], executor_ref: 'agent-real', model: 'recorded-model', reasoning_effort: 'high', started_at: 'exec-start', finished_at: 'exec-finish' };
  for (const locale of ['en', 'ko']) {
    const html = render(view({ status: 'Completed', execution_timing: timing, active_execution: execution, owned_paths: [], depends_on: [] }), locale);
    assert.match(html, new RegExp(locale === 'ko' ? '0초' : '0s'));
    assert.ok(!html.includes(translate(locale, 'notMeasured')));
    for (const value of Object.values(execution).flat()) assert.ok(html.includes(escape(value)), value);
    assert.ok(html.includes(translate(locale, 'wbElapsedSeconds')));
    assert.match(html, /data-value-type="null"/);
    assert.match(html, /wb-value-type">(?:Array · 0 items|배열 · 0개)/);
    assert.ok(render(view({ execution_timing: null }), locale).includes(translate(locale, 'notMeasured')));
  }
  const nonTask = render(view({ kind: 'plan', execution_timing: undefined }));
  assert.doesNotMatch(nonTask, /Not measured/);
});

test('related rows follow actual references in the selected source and RUN, including inverse references', () => {
  const plan = { id: 2, stable_id: 'PLAN-002', kind: 'plan', title: 'Actual parent plan' };
  const dependency = { id: 11, stable_id: 'TASK-011', kind: 'task', title: 'Actual prerequisite' };
  const finding = { id: 18, stable_id: 'FINDING-018', kind: 'finding', title: 'Actual referencing finding', related_ids: 'TASK-012' };
  const unrelated = { id: 9, stable_id: 'PLAN-009', kind: 'plan', title: 'Unrelated plan must stay absent' };
  const foreign = { id: 99, stable_id: 'TASK-999', kind: 'task', title: 'Foreign source record must stay absent', source_db: '/foreign.sqlite3' };
  const wrongRun = { id: 98, stable_id: 'TASK-998', kind: 'task', title: 'Foreign RUN record must stay absent', run_id: 'another-run' };
  const context = snapshot({ plans: [plan, unrelated], tasks: [base, dependency, foreign, wrongRun], findings: [finding] });
  const html = render(view({ spec_id: plan.stable_id, depends_on: [dependency.stable_id, 'TASK-404', foreign.stable_id, wrongRun.stable_id], related_ids: 'FINDING-018' }, context));
  for (const record of [plan, dependency, finding]) assert.ok(html.includes(record.title));
  for (const record of [unrelated, foreign, wrongRun]) assert.ok(!html.includes(record.title));
  assert.match(html, /<span class="wb-mono">TASK-404<\/span>/);
  assert.equal((html.match(/class="wb-related-record"/g) || []).length, 3);
  for (const changed of [{ ...context, run: { ...run, source_db: '/foreign.sqlite3' } }, { ...context, run: { ...run, id: 'wrong-run' } }]) {
    assert.doesNotMatch(render(view({ spec_id: plan.stable_id, depends_on: [dependency.stable_id] }, changed)), /wb-related-records|Actual parent plan|Actual prerequisite/);
  }
  assert.doesNotMatch(render(view({ spec_id: plan.stable_id })), /wb-related-records/);
});

test('navigation handlers preserve the actual source for record, RUN and archive actions', () => {
  const react = { ...React, useContext: (context) => context._currentValue, useState: (initial) => [typeof initial === 'function' ? initial() : initial, () => {}], useEffect() {}, useMemo: (factory) => factory() };
  const Component = load(react).RecordDetail;
  const commands = []; let backed = 0;
  const parent = { id: 2, stable_id: 'PLAN-002', kind: 'plan', title: 'Actual parent plan' };
  const props = { view: view({ spec_id: parent.stable_id, archive_id: 'archive-real' }, snapshot({ plans: [parent] })), send: (message) => commands.push(message), back: () => backed++ };
  function nodes(node) {
    if (!node || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(nodes);
    return [node, ...(typeof node.type === 'function' ? nodes(node.type(node.props)) : nodes(node.props?.children))];
  }
  const tree = nodes(Component(props));
  const button = (focus) => tree.find((node) => node.type === 'button' && node.props['data-wb-focus'] === focus);
  button('related-row:2').props.onClick();
  button('related:2').props.onClick();
  button('record-run').props.onClick();
  tree.find((node) => node.props?.className === 'wb-reading-archive').props.onClick();
  button('back').props.onClick();
  assert.deepEqual(commands, [
    { command: 'openSearchResult', itemId: 2, source_db: run.source_db },
    { command: 'openSearchResult', itemId: 2, source_db: run.source_db },
    { command: 'openRun', runId: run.id, source_db: run.source_db },
    { command: 'openArchive', archiveId: 'archive-real', source_db: run.source_db }
  ]);
  assert.equal(backed, 1);
  assert.equal(button('back').props.title, 'Back');
});

test('PLAN semantic fields are visible reading sections rather than hidden additional JSON', () => {
  const fields = { kind: 'plan', summary: 'Plan summary', objective: 'Plan purpose', requirements_trace: 'Real requirements', selected_approach: 'Chosen approach', affected_files: 'src/viewer', execution_order: 'First build then verify', risks: 'Real constraint', validation: 'Verify real output', approval_needs: 'Already authorized', notes: 'Original note' };
  const labels = [['summary','Summary'],['objective','Objective'],['requirements_trace','Requirements trace'],['selected_approach','Selected approach'],['affected_files','Affected files'],['execution_order','Execution order'],['risks','Risks'],['validation','Validation'],['approval_needs','Approval needs'],['notes','Notes']];
  fields.body = labels.map(([key,label]) => `### ${label}\n${fields[key]}`).join('\n\n');
  for (const locale of ['en','ko']) {
    const html = render(view(fields), locale);
    const visible = html.split('class="wb-record-disclosures"')[0];
    for (const [key] of labels) {
      assert.ok(visible.includes(fields[key]));
      assert.equal(visible.split(escape(fields[key])).length - 1, 1, `${key} appears once in the reading body`);
      assert.ok(!html.includes(`class="wb-value-key">${key}</span>`), `${key} is promoted out of additional fields`);
    }
    assert.doesNotMatch(html, /data-wb-focus="back"/);
    assert.ok(!html.includes(`<span>${translate(locale,'execution')}</span>`), 'no artificial execution section');
  }
});

test('partial detail retains result RUN identity and arbitrary nested executor fields', () => {
  const html = render(view({ run_id: undefined, active_execution: { execution_id: 'actual', future: { field: 0 } } }));
  assert.ok(html.includes(`>${run.id}</button>`));
  assert.ok(html.includes('wb-value-key">future</span>'));
  assert.ok(html.includes('wb-value-key">field</span>'));
});

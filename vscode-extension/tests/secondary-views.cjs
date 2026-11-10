const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const filename = path.join(__dirname, 'secondary-views-render.cjs');
const output = buildSync({
  stdin: {
    contents:
      "export { SecondaryView, PageLoading } from './src/webview/workbench/SecondaryViews'; export { I18nProvider } from './src/webview/i18n';",
    resolveDir: path.resolve(__dirname, '..')
  },
  bundle: true,
  write: false,
  platform: 'node',
  format: 'cjs',
  jsx: 'automatic',
  external: ['react', 'react-dom']
}).outputFiles[0].text;
const compiled = new Module(filename, module);
compiled.filename = filename;
compiled.paths = module.paths;
compiled._compile(output, filename);
const { SecondaryView, PageLoading, I18nProvider } = compiled.exports;
const render = (locale, view) =>
  renderToStaticMarkup(
    React.createElement(I18nProvider, { locale }, React.createElement(SecondaryView, { view, send() {}, back() {} }))
  );
const archive = {
  id: 'archive-a',
  slug: 'Saved workflow',
  summary: 'Actual archive summary',
  created_at: '2026-10-08T00:00:00Z',
  source_db: '/source-a/tapl.db',
  run_id: 'run-a',
  run_slug: 'Original run',
  request_summary: 'Original request',
  run_created_at: '2026-10-01T00:00:00Z',
  run_updated_at: '2026-10-07T00:00:00Z',
  run_archived_at: '2026-10-08T00:00:00Z'
};
const items = [
  {
    id: 1,
    stable_id: 'PLAN-001',
    kind: 'plan',
    title: 'Plan title',
    body: 'Plan body',
    source: 'agent',
    run_id: 'run-a'
  },
  {
    id: 2,
    stable_id: 'TASK-001',
    kind: 'task',
    title: 'Task title',
    status: 'Completed',
    body: 'Task body',
    execution_timing: {
      started_at: '2026-10-01T00:00:00Z',
      finished_at: '2026-10-01T00:01:00Z',
      elapsed_seconds: 60,
      running_since: null,
      as_of: '2026-10-08T00:00:00Z'
    }
  },
  {
    stable_id: 'CUSTOM-001',
    kind: 'custom-kind',
    title: 'Custom record title',
    body: 'Custom body <script>x()</script>',
    custom_fields: { flags: { enabled: false, count: 0 }, unset: null, labels: ['alpha', 'beta'] },
    updated_at: '2026-10-07T12:00:00Z'
  }
];
const events = [
  {
    event_type: 'second_event',
    tool_name: 'tapl_update',
    mode: 'strict',
    message: 'Later <img src=x>',
    created_at: '2026-10-08T02:00:00Z',
    source_db: '/source-b/tapl.db'
  },
  {
    event_type: 'first_event',
    tool_name: 'tapl_start',
    mode: 'planned',
    message: 'Earlier event',
    created_at: '2026-10-08T01:00:00Z'
  }
];

function assertWorkbenchPage(html) {
  assert.equal((html.match(/<h1 /g) || []).length, 1);
  assert.ok(html.includes('data-wb-page-heading'));
  assert.doesNotMatch(html, /tapl-card|tapl-topbar|tapl-metric-grid|tapl-eyebrow|<script>|<img src=x>/);
}

test('archive fallback keeps every record kind, custom value, summary, timestamp and source', () => {
  for (const locale of ['en', 'ko']) {
    const html = render(locale, { type: 'archive', archive, detail: { archive, items, events } });
    assertWorkbenchPage(html);
    for (const value of [
      'Actual archive summary',
      'Original request',
      'Original run',
      'run-a',
      archive.source_db,
      'PLAN-001',
      'Plan body',
      'TASK-001',
      'Task body',
      'custom-kind',
      'CUSTOM-001',
      'Custom record title',
      'Custom body &lt;script&gt;x()&lt;/script&gt;',
      'wb-value-key">enabled</span>',
      'wb-value-key">count</span>',
      'null',
      'alpha',
      'beta',
      'elapsed_seconds',
      locale === 'ko' ? '1분' : '1m',
      'data-status="Completed"'
    ])
      assert.ok(html.includes(value), value);
    for (const value of [
      archive.created_at,
      archive.run_created_at,
      archive.run_updated_at,
      archive.run_archived_at,
      items[2].updated_at
    ])
      assert.ok(html.includes(`dateTime="${value}"`));
    assert.equal((html.match(/class="wb-secondary-record"/g) || []).length, 3);
  }
});

test('missing archive details remain distinct from an available empty archive', () => {
  for (const [locale, unavailable, empty] of [
    ['en', 'Archive details unavailable.', 'No records on this page.'],
    ['ko', '아카이브 상세 정보를 사용할 수 없습니다.', '이 페이지에 표시할 기록이 없습니다.']
  ]) {
    const missing = render(locale, { type: 'archive', archive });
    const available = render(locale, { type: 'archive', archive, detail: { archive, items: [], events: [] } });
    assert.ok(missing.includes(unavailable), missing);
    assert.ok(!missing.includes(empty));
    assert.ok(available.includes(empty), available);
    assert.ok(!available.includes(unavailable));
  }
});

test('archive event rows are chronological, escaped and inspectable with their complete fields', () => {
  for (const locale of ['en', 'ko']) {
    const html = render(locale, { type: 'archiveEvents', archive, detail: { archive, items, events } });
    assertWorkbenchPage(html);
    assert.ok(html.includes('<ol class="wb-secondary-events">'));
    assert.ok(html.indexOf('first_event') < html.indexOf('second_event'));
    for (const value of [
      'tapl_update',
      'strict',
      'Later &lt;img src=x&gt;',
      '/source-b/tapl.db',
      'wb-secondary-inspect'
    ])
      assert.ok(html.includes(value), value);
    for (const event of events) assert.ok(html.includes(`dateTime="${event.created_at}"`));
  }
});

test('debug metadata and diagnostics retain counts, schema and active execution data', () => {
  const status = {
    active_run: { id: 'run-live', slug: 'Live workflow', status: 'active' },
    session_id: 'session-live',
    source_db: '/live/tapl.db',
    task_counts: { Pending: 3, Blocked: 2 },
    incomplete_tasks: 5,
    plans: [items[0]],
    tasks: [items[1]],
    findings: [],
    counts: { plans: 11, tasks: 12, findings: 13, archives: 14, active_batches: 1, active_executions: 2 },
    recent_events: events,
    schema: { version: '42', memories: 'supported' },
    active_batches: [{ batch: { batch_id: 'batch-live', state: 'running' }, executions: [] }],
    active_executions: [{ execution_id: 'execution-live', task_id: 'TASK-001', execution_state: 'running' }]
  };
  for (const locale of ['en', 'ko']) {
    const html = render(locale, { type: 'debug', status });
    assertWorkbenchPage(html);
    for (const value of [
      'Live workflow',
      'session-live',
      '/live/tapl.db',
      '>11<',
      '>12<',
      '>13<',
      '>42<',
      'supported',
      'batch-live',
      'execution-live',
      'wb-value-key">archives</span>', '>14<'
    ])
      assert.ok(html.includes(value), value);
    assert.ok(html.includes('<details class="wb-secondary-disclosure">'));
    assert.ok(!html.includes('<details class="wb-secondary-disclosure" open'));
  }
});

test('legacy search keeps hybrid mode, snippets, source identity and missing-id records', () => {
  for (const locale of ['en', 'ko']) {
    const html = render(locale, {
      type: 'search',
      search: {
        query: 'needle',
        mode: 'hybrid',
        results: [
          {
            id: 12,
            stable_id: 'FIND-012',
            kind: 'finding',
            title: 'Readable result',
            status: 'Blocked',
            snippet: '<svg>literal</svg>',
            source: 'agent',
            search_source: 'vector',
            source_db: '/source-c/tapl.db',
            run_id: 'run-c',
            score: 0.75
          },
          { stable_id: 'OLD-1', kind: 'legacy', title: 'Legacy record', search_source: 'text' }
        ]
      }
    });
    assertWorkbenchPage(html);
    for (const value of [
      'hybrid',
      'needle',
      'FIND-012',
      'Readable result',
      '&lt;svg&gt;literal&lt;/svg&gt;',
      '/source-c/tapl.db',
      'run-c',
      '0.75',
      'OLD-1',
      'Legacy record',
      'data-status="Blocked"'
    ])
      assert.ok(html.includes(value), value);
    assert.ok(html.includes('<article class="wb-search-result">'));
  }
});

test('error and loading pages share workbench headings and preserve recovery controls', () => {
  for (const [locale, error, workspace] of [
    ['en', 'Error', 'Choose a workspace'],
    ['ko', '오류', '워크스페이스 선택']
  ]) {
    const html = render(locale, { type: 'error', message: 'Failed <script>escape</script>' });
    assertWorkbenchPage(html);
    assert.ok(html.includes('role="alert"'));
    assert.ok(html.includes('Failed &lt;script&gt;escape&lt;/script&gt;'));
    assert.ok(html.includes(error));
    assert.ok(html.includes(workspace), html);
    const loading = renderToStaticMarkup(
      React.createElement(I18nProvider, { locale }, React.createElement(PageLoading))
    );
    assertWorkbenchPage(loading);
    assert.ok(loading.includes('role="status"'));
  }
});

test('direct secondary pages do not fabricate a Back destination', () => {
  const html = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      { locale: 'en' },
      React.createElement(SecondaryView, { view: { type: 'archive', archive }, send() {} })
    )
  );
  assert.ok(!html.includes('wb-back'));
});

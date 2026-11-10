const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

// Bundle the actual shared screen, keeping React shared with the server renderer.
const filename = path.join(__dirname, 'memory-view-render.cjs');
const output = buildSync({
  stdin: {
    contents:
      "export { MemoryView } from './src/webview/MemoryView'; export { I18nProvider } from './src/webview/i18n';",
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
const { MemoryView, I18nProvider } = compiled.exports;

function render(locale, diagnostics) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      { locale },
      React.createElement(MemoryView, {
        supported: true,
        send() {},
        view: {
          type: 'memories',
          query: 'missing',
          offset: 0,
          limit: 50,
          total: 0,
          memories: [],
          diagnostics
        }
      })
    )
  );
}

test('shared memory screen distinguishes stored and matched counts in both locales', () => {
  for (const [locale, stored, matched] of [
    ['en', 'Total stored', 'Matching this query'],
    ['ko', '전체 저장 수', '현재 검색 일치 수']
  ]) {
    const html = render(locale, { stored_count: 4, matched_count: 0, last_capture_error: null });
    assert.ok(html.includes(`<dt>${stored}</dt><dd>4</dd>`));
    assert.ok(html.includes(`<dt>${matched}</dt><dd>0</dd>`));
    assert.ok(!html.includes('Most recent capture failure'));
  }
});

test('capture failure text remains readable and escaped, without mutation controls', () => {
  const html = render('en', {
    stored_count: 0,
    matched_count: 0,
    injected_count: 0,
    last_capture_error: {
      run_id: 'run-1',
      slot: 2,
      code: 'invalid_memory_note',
      message: '<script>alert("failed")</script>',
      created_at: '2026-09-16T00:00:00Z'
    }
  });
  assert.ok(html.includes('Most recent capture failure'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('Run run-1 · Slot 2'));
  assert.ok(html.includes('Historical diagnostic'));
  assert.ok(html.includes('<dt>Hints injected</dt><dd>0</dd>'));
  assert.doesNotMatch(html, /<button[^>]*>[^<]*(?:Delete|Update|Retry|Skip)/);
});

test('older hosts without diagnostics preserve the empty search screen', () => {
  const html = render('en');
  assert.ok(html.includes('No memories match this search.'));
  assert.ok(!html.includes('Memory diagnostics'));
});

function renderView(locale, view, supported = true) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      { locale },
      React.createElement(MemoryView, { supported, send() {}, back() {}, view })
    )
  );
}
const memory = {
  source_db: '/source-a/.tapl/tapl.db',
  id: 'MEM-9',
  note: 'Keep the real canonical note.\n<script>source()</script>',
  cue: ['canonical', 'release'],
  matched_cues: ['release'],
  state: 'superseded',
  revision: 4,
  source: { run_id: 'run-9', item_id: 7, archive_id: 'archive-9', title: 'Source title', kind: 'item' },
  created_at: '2026-10-01T01:02:03Z',
  updated_at: '2026-10-02T01:02:03Z',
  last_reinforced_at: '2026-10-03T01:02:03Z',
  half_life_days: 23,
  strength: 0.72,
  source_available: true,
  source_record: {
    kind: 'item',
    item: {
      id: 7,
      stable_id: 'FIND-007',
      kind: 'finding',
      title: 'Original finding',
      body: 'Source body <b>literal</b>',
      custom_fields: { nested: { approved: false, count: 0 }, empty: null }
    }
  }
};

test('memory cards use canonical notes and retain cues, source and actual use in both locales', () => {
  for (const [locale, sourceLabel, recallLabel] of [
    ['en', 'Original source', 'Easy to recall'],
    ['ko', '원본 출처', '쉽게 떠오름']
  ]) {
    const html = renderView(locale, {
      type: 'memories',
      query: '',
      offset: 20,
      limit: 20,
      total: 45,
      memories: [memory]
    });
    for (const value of [
      'wb-memory-grid',
      'wb-memory-card',
      'Keep the real canonical note.\n&lt;script&gt;source()&lt;/script&gt;',
      'is-matched',
      'Source title',
      memory.source_db,
      sourceLabel,
      recallLabel
    ])
      assert.ok(html.includes(value), value);
    assert.ok(html.includes(`dateTime="${memory.last_reinforced_at}"`));
    assert.equal((html.match(/<h1 /g) || []).length, 1);
    assert.doesNotMatch(html, /tapl-card|tapl-topbar|tapl-eyebrow|<script>|<b>literal/);
  }
});

test('memory detail keeps provenance, precise strength, revision, decay and safe source preview', () => {
  for (const locale of ['en', 'ko']) {
    const html = renderView(locale, { type: 'memory', memoryId: memory.id, source_db: memory.source_db, memory });
    for (const value of [
      'wb-secondary-reading',
      'wb-secondary-properties',
      'MEM-9',
      'run-9',
      'archive-9',
      '0.72',
      '>23<',
      '>4<',
      'FIND-007',
      'Original finding',
      'Source body &lt;b&gt;literal&lt;/b&gt;',
      'wb-value-key">approved</span>',
      'wb-value-key">count</span>',
      'wb-value-key">empty</span>'
    ])
      assert.ok(html.includes(value), value);
    for (const value of [memory.created_at, memory.updated_at, memory.last_reinforced_at])
      assert.ok(html.includes(`dateTime="${value}"`));
    assert.equal((html.match(/<h1 /g) || []).length, 1);
  }
});

test('memory unsupported, deleted and missing-source states stay distinct and read-only', () => {
  const unsupported = renderView(
    'en',
    { type: 'memories', memories: [], query: '', offset: 0, limit: 20, total: 0 },
    false
  );
  assert.ok(unsupported.includes('Memory browsing is not available in this host.'));
  assert.doesNotMatch(unsupported, /type="search"/);
  for (const value of [null, { ...memory, state: 'deleted' }]) {
    const html = renderView('en', { type: 'memory', memoryId: 'MEM-9', memory: value });
    assert.ok(html.includes('This memory is no longer available.'));
    assert.ok(!html.includes('Keep the real canonical note'));
  }
  const missingSource = renderView('en', {
    type: 'memory',
    memoryId: 'MEM-9',
    memory: { ...memory, source_available: false, source_record: undefined }
  });
  assert.ok(missingSource.includes('Original source is unavailable.'));
  assert.ok(missingSource.includes('Keep the real canonical note'));
  assert.ok(!missingSource.includes('Open original source</button>'));
});

test('memory source fallback preserves both run summaries and metadata', () => {
  const html = renderView('en', {
    type: 'memorySource',
    memoryId: 'MEM-9',
    source_db: memory.source_db,
    run: {
      id: 'run-source',
      slug: 'Original run',
      request_summary: 'Request text',
      result_summary: 'Result text',
      status: 'archived',
      session_id: 'session-source',
      work_type: 'review',
      workflow_mode: 'planned',
      record_mode: 'full',
      record_count: 9,
      writable: false
    }
  });
  for (const value of [
    'run-source',
    'Original run',
    'Request text',
    'Result text',
    'archived',
    'session-source',
    'review',
    'planned',
    'full',
    '>9<',
    'false',
    memory.source_db
  ])
    assert.ok(html.includes(value), value);
  assert.equal((html.match(/<h1 /g) || []).length, 1);
});

test('direct memory entry shows no Back button without a navigation trail', () => {
  const html = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      { locale: 'en' },
      React.createElement(MemoryView, {
        supported: false,
        view: { type: 'memories', query: '', offset: 0, limit: 20, total: 0, memories: [] },
        send() {}
      })
    )
  );
  assert.ok(!html.includes('wb-back'));
});

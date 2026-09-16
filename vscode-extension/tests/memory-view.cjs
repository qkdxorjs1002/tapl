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
  stdin: { contents: "export { MemoryView } from './src/webview/MemoryView'; export { I18nProvider } from './src/webview/i18n';", resolveDir: path.resolve(__dirname, '..') },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react-dom']
}).outputFiles[0].text;
const compiled = new Module(filename, module);
compiled.filename = filename;
compiled.paths = module.paths;
compiled._compile(output, filename);
const { MemoryView, I18nProvider } = compiled.exports;

function render(locale, diagnostics) {
  return renderToStaticMarkup(React.createElement(I18nProvider, { locale },
    React.createElement(MemoryView, { supported: true, send() {}, view: {
      type: 'memories', query: 'missing', offset: 0, limit: 50, total: 0, memories: [], diagnostics
    } })));
}

test('shared memory screen distinguishes stored and matched counts in both locales', () => {
  for (const [locale, stored, matched] of [['en', 'Total stored', 'Matching this query'], ['ko', '전체 저장 수', '현재 검색 일치 수']]) {
    const html = render(locale, { stored_count: 4, matched_count: 0, last_capture_error: null });
    assert.ok(html.includes(`<dt>${stored}</dt><dd>4</dd>`));
    assert.ok(html.includes(`<dt>${matched}</dt><dd>0</dd>`));
    assert.ok(!html.includes('Most recent capture failure'));
  }
});

test('capture failure text remains readable and escaped, without mutation controls', () => {
  const html = render('en', { stored_count: 0, matched_count: 0, injected_count: 0,
    last_capture_error: { run_id: 'run-1', slot: 2, code: 'invalid_memory_note', message: '<script>alert("failed")</script>', created_at: '2026-09-16T00:00:00Z' }
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

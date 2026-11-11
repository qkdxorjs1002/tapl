const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const filename = path.join(__dirname, 'session-view-render.cjs');
const output = buildSync({
  loader: { '.css': 'empty' },
  stdin: { contents: "export { App } from './src/webview/App';", resolveDir: path.resolve(__dirname, '..') },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react-dom']
}).outputFiles[0].text;

const run = { id: 'run-b', session_id: 'session-b', request_summary: 'Remaining work' };

function render(activeRun, runs = [run]) {
  global.acquireVsCodeApi = () => ({
    getState: () => ({ locale: 'en', layout: 'auto', view: {
      type: 'overview', archives: [], searchQuery: '', status: {
        session_id: activeRun ? 'session-b' : 'session-a', active_run: activeRun ? run : null,
        active_runs: runs, tasks: [], plans: [], findings: [], task_counts: {}, incomplete_tasks: 0
      }
    } }),
    setState() {}, postMessage() {}
  });
  try {
    const compiled = new Module(filename, module);
    compiled.filename = filename;
    compiled.paths = module.paths;
    compiled._compile(output, filename);
    return renderToStaticMarkup(React.createElement(compiled.exports.App));
  } finally {
    delete global.acquireVsCodeApi;
  }
}

test('the remaining RUN stays keyboard-selectable after the selected RUN ends', () => {
  const html = render(false);
  assert.match(html, /role="tablist" aria-label="RUN"/);
  assert.match(html, /aria-selected="false"[^>]*id="wb-run-tab-0"[^>]*tabindex="0"/);
  assert.match(html, /Remaining work/);
  assert.match(html, /No active RUN/);
});

test('one selected RUN keeps the header tab and shared navigation visible', () => {
  const html = render(true);
  assert.match(html, /aria-selected="true"[^>]*id="wb-run-tab-0"/);
  assert.match(html, /role="tabpanel" aria-labelledby="wb-run-tab-0"/);
  assert.match(html, /wb-sidebar/);
  assert.match(html, /TASK status/);
  assert.doesNotMatch(html, /tapl-hero|<select/);
});

test('multiple RUNs keep full titles and one keyboard entry', () => {
  const title = '긴 작업 제목 '.repeat(12);
  const html = render(true, [run, { id: 'run-c', session_id: 'session-c', request_summary: title }]);
  assert.match(html, /aria-selected="false"[^>]*id="wb-run-tab-1"[^>]*tabindex="-1"/);
  assert.ok(html.includes(`title="${title.trim()}\nrun-c"`));
  assert.equal((html.match(/role="tab"/g) || []).length, 2);
});

test('no RUNs keeps the navigation and an actionable empty state', () => {
  const html = render(false, []);
  assert.match(html, /wb-run-tabs tabs/);
  assert.match(html, /No active RUN/);
  assert.match(html, /Record search/);
  assert.doesNotMatch(html, /role="tab"/);
});

test('the selected RUN remains a tab when the inventory omits it', () => {
  assert.match(render(true, []), /aria-selected="true"[^>]*id="wb-run-tab-0"/);
});

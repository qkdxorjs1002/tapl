const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const filename = path.join(__dirname, 'session-view-render.cjs');
const output = buildSync({
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

test('the remaining RUN stays selectable after the previously selected RUN ends', () => {
  const html = render(false);
  assert.match(html, /role="tablist" aria-label="active run"/);
  assert.match(html, /id="tapl-run-tab-run-b"[^>]*aria-selected="false"[^>]*tabindex="0"/);
  assert.match(html, /tapl-run-tab-title">Remaining work/);
  assert.match(html, /aria-label="No active run"/);
});

test('one selected RUN keeps the top-level tab visible', () => {
  const html = render(true);
  assert.match(html, /id="tapl-run-tab-run-b"[^>]*aria-selected="true"/);
  assert.match(html, /role="tabpanel" aria-labelledby="tapl-run-tab-run-b"/);
  assert.ok(html.indexOf('class="tapl-run-tabs"') < html.indexOf('class="tapl-hero"'));
  assert.doesNotMatch(html, /<select/);
});

test('multiple RUNs have separate tabs with full titles and one keyboard entry', () => {
  const title = '신규 개발·운영 Site-to-Site VPN 연결2개의 과금 중지를 위해 비밀값 확인 '.repeat(4);
  const html = render(true, [run, { id: 'run-c', session_id: 'session-c', request_summary: title }]);
  assert.match(html, /id="tapl-run-tab-run-c"[^>]*aria-selected="false"[^>]*tabindex="-1"/);
  assert.ok(html.includes(`title="${title}\nsession-c"`));
  assert.ok(html.includes(`tapl-run-tab-title">${title}</span>`));
});

test('no RUNs keeps a disabled empty tab in the same top-level slot', () => {
  const html = render(false, []);
  assert.match(html, /class="tapl-run-tab"[^>]*role="tab"[^>]*disabled=""/);
  assert.match(html, /tapl-run-tab-title">No active run/);
  assert.ok(html.indexOf('class="tapl-run-tabs"') < html.indexOf('class="tapl-hero"'));
});

test('the selected RUN remains a tab when the inventory does not include it', () => {
  assert.match(render(true, []), /id="tapl-run-tab-run-b"[^>]*aria-selected="true"/);
});

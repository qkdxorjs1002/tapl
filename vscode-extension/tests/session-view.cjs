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

function render(activeRun) {
  const run = { id: 'run-b', session_id: 'session-b', request_summary: 'Remaining work' };
  global.acquireVsCodeApi = () => ({
    getState: () => ({ locale: 'en', layout: 'auto', view: {
      type: 'overview', archives: [], searchQuery: '', status: {
        session_id: activeRun ? 'session-b' : 'session-a', active_run: activeRun ? run : null,
        active_runs: [run], tasks: [], plans: [], findings: [], task_counts: {}, incomplete_tasks: 0
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
  assert.match(html, /<select/);
  assert.match(html, /<option value="run-b">Remaining work/);
  assert.match(html, /<option value="" disabled="" selected="">No active run/);
});

test('one selected RUN needs no redundant selector', () => {
  assert.doesNotMatch(render(true), /<option value="run-b">/);
});

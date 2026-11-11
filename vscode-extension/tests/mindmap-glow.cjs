const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const filename = path.join(__dirname, 'mindmap-glow-render.cjs');
const output = buildSync({
  entryPoints: [path.join(__dirname, '../src/webview/workbench/MindmapEdges.tsx')],
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
  external: ['react', 'react-dom']
}).outputFiles[0].text;
const compiled = new Module(filename, module);
compiled.filename = filename;
compiled.paths = module.paths;
compiled._compile(output, filename);
const { MindmapEdge } = compiled.exports;
const css = fs.readFileSync(path.join(__dirname, '../src/webview/workbench/run-mindmap.css'), 'utf8');
const edge = { from: 'plan', to: 'task', path: 'M 0 0 C 50 0 50 100 100 100', start: { x: 0, y: 0 } };
const render = (props) => renderToStaticMarkup(React.createElement(MindmapEdge, props));
const classes = (html) => [...html.matchAll(/<path class="([^"]+)"/g)].map(match => match[1]);
function rule(selector) {
  const start = css.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `missing rule: ${selector}`);
  return css.slice(css.indexOf('{', start) + 1, css.indexOf('}', start));
}

test('only executing edges gain light layers, even when a static relation is hovered', () => {
  for (const emphasis of [undefined, 'active', 'dim']) {
    const html = render({ edge, emphasis, relation: 'source' });
    assert.deepEqual(classes(html), ['wb-mm-edge']);
    assert.match(html, /class="wb-mm-pulse"/);
    assert.doesNotMatch(html, /data-flow=|wb-mm-glass-path|wb-mm-flow/);
  }
  const html = render({ edge: { ...edge, flowing: true }, emphasis: 'active' });
  assert.match(html, /data-flow="running"/);
  assert.deepEqual(classes(html), [
    'wb-mm-edge', 'wb-mm-glass-path wb-mm-tube-channel', 'wb-mm-glass-path wb-mm-tube-reflection',
    'wb-mm-glass-path wb-mm-flow-glow', 'wb-mm-glass-path wb-mm-flow-halo',
    'wb-mm-glass-path wb-mm-flow-tail', 'wb-mm-glass-path wb-mm-flow-core'
  ]);
  assert.equal((html.match(/pathLength="100"/g) ?? []).length, 4);
  assert.ok(html.indexOf('wb-mm-edge"') < html.indexOf('wb-mm-pulse wb-mm-flow'));
  assert.doesNotMatch(html, /<filter|filter=|<defs/);
});

test('each graph edge retains a primary path followed by its pulse in graph order', () => {
  const html = renderToStaticMarkup(React.createElement('svg', null,
    [false, true, false, true].map((flowing, index) => React.createElement(MindmapEdge, {
      key: index, edge: { ...edge, from: `plan-${index}`, to: `task-${index}`, flowing }
    }))));
  const order = [...html.matchAll(/data-from="([^"]+)"|class="(wb-mm-edge|wb-mm-pulse(?: wb-mm-flow)?)"/g)]
    .map(match => match[1] ?? match[2]);
  assert.deepEqual(order, [
    'plan-0', 'wb-mm-edge', 'wb-mm-pulse',
    'plan-1', 'wb-mm-edge', 'wb-mm-pulse wb-mm-flow',
    'plan-2', 'wb-mm-edge', 'wb-mm-pulse',
    'plan-3', 'wb-mm-edge', 'wb-mm-pulse wb-mm-flow'
  ]);
});

test('light uses a progress-colored outer spread and a luminous core across theme button colors', () => {
  const core = rule('.wb-mindmap').match(/--mm-flow-core:\s*([^;]+)/)?.[1];
  assert.match(core, /var\(--mm-progress\)/);
  assert.match(core, /#fff\b/);
  assert.doesNotMatch(core, /--tapl-primary-content/);
  const layers = ['glow', 'halo', 'tail', 'core'].map(name => rule(`.wb-mm-flow-${name}`));
  const widths = layers.map(body => Number(body.match(/stroke-width:\s*([\d.]+)/)?.[1]));
  assert.ok(widths.every((width, index) => width > 0 && (!index || width < widths[index - 1])),
    'concentric spread narrows toward the core');
  layers.slice(0, -1).forEach(body => assert.match(body, /stroke:\s*var\(--mm-progress\)/));
  layers.forEach(body => {
    assert.match(body, /--mm-flow-progress/);
    assert.doesNotMatch(body, /filter\s*:/, 'glow must not allocate per-edge blur surfaces');
  });
});

test('reduced motion hides the complete light group and high contrast retains its connection line', () => {
  assert.match(rule(".wb-mindmap[data-reduced-motion='true'] :is(.wb-mm-pulse, .wb-mm-flow)"), /display:\s*none/);
  const media = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'));
  assert.match(media, /\.wb-mm-pulse,\s*\.wb-mm-flow\s*\{\s*display:\s*none/);
  const host = 'html:not([data-tapl-theme]) > body:is(.vscode-high-contrast, .vscode-high-contrast-light)';
  assert.match(rule(`${host} .wb-mm-edge-running .wb-mm-edge`), /stroke:\s*var\(--mm-line\)/);
  assert.match(rule(`${host} :is(.wb-mm-flow-glow, .wb-mm-flow-halo)`), /display:\s*none/);
});

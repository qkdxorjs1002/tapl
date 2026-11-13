const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const filename = path.join(__dirname, 'mindmap-relations-render.cjs');
const output = buildSync({
  stdin: {
    contents: `
      export * from './mindmapRelations';
      export { mindmapRunActiveKeys } from './mindmapCamera';
      export * from './mindmap';
      export * from './memoryMindmapGraph';
      export { RunMindmap } from './RunMindmap';
      export { MemoryMindmap } from './MemoryMindmap';
      export { I18nProvider } from '../i18n';
    `,
    resolveDir: path.join(__dirname, '../src/webview/workbench')
  },
  loader: { '.css': 'empty' },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
  external: ['react', 'react-dom']
}).outputFiles[0].text;
const compiled = new Module(filename, module);
compiled.filename = filename;
compiled.paths = module.paths;
compiled._compile(output, filename);
const {
  buildMindmapRelationIndex, relatedMindmapNodes, mindmapRunActiveKeys,
  buildRunMindmap, buildMemoryMindmap, RunMindmap, MemoryMindmap, I18nProvider
} = compiled.exports;

const sorted = (set) => [...set].sort();
const graphOf = (keys, pairs) => ({
  nodes: keys.map(key => ({ key })), edges: pairs.map(([from, to]) => ({ from, to }))
});

test('DAG highlights every shared ancestor and descendant without following siblings or co-parents', () => {
  const graph = graphOf(
    ['workspace', 'source-a', 'source-b', 'memory-a', 'memory-b', 'shared', 'only-a', 'isolated'],
    [['workspace', 'source-a'], ['workspace', 'source-b'],
      ['source-a', 'memory-a'], ['source-b', 'memory-b'],
      ['memory-a', 'shared'], ['memory-b', 'shared'], ['memory-a', 'only-a']]
  );
  const index = buildMindmapRelationIndex(graph);
  assert.deepEqual(sorted(relatedMindmapNodes(index, 'shared')),
    ['memory-a', 'memory-b', 'shared', 'source-a', 'source-b', 'workspace']);
  assert.deepEqual(sorted(relatedMindmapNodes(index, 'memory-a')),
    ['memory-a', 'only-a', 'shared', 'source-a', 'workspace']);
  assert.deepEqual(sorted(relatedMindmapNodes(index, 'isolated')), ['isolated']);
  assert.equal(relatedMindmapNodes(index), undefined);
  assert.equal(relatedMindmapNodes(index, 'stale-node'), undefined);
});

test('RUN ancestors use node parents while descendants use actual outgoing edges', () => {
  const graph = {
    nodes: [{ key: 'run' }, { key: 'plan', parent: 'run' },
      { key: 'task', parent: 'plan' }, { key: 'sibling', parent: 'plan' },
      { key: 'dangling', parent: 'missing' }],
    edges: [{ from: 'plan', to: 'task' }, { from: 'plan', to: 'sibling' }]
  };
  const index = buildMindmapRelationIndex(graph, 'node-parent');
  assert.deepEqual(sorted(relatedMindmapNodes(index, 'task')), ['plan', 'run', 'task']);
  assert.deepEqual(sorted(relatedMindmapNodes(index, 'plan')), ['plan', 'run', 'sibling', 'task']);
  assert.deepEqual(sorted(relatedMindmapNodes(index, 'dangling')), ['dangling', 'missing']);
});

test('automatic execution seeds exclude fitted parents and traverse shared ancestry only once', () => {
  const nodes = [
    { key: 'run', kind: 'run' },
    { key: 'plan-a', kind: 'plan', parent: 'run', status: 'In Progress' },
    { key: 'plan-b', kind: 'plan', parent: 'run', status: 'In Progress' },
    ...Array.from({ length: 1000 }, (_, i) => ({ key: `task-${i}`, kind: 'task', parent: 'plan-a', status: 'In Progress' })),
    { key: 'idle', kind: 'task', parent: 'plan-a', status: 'Pending' }
  ];
  const graph = { nodes, edges: nodes.filter(node => node.parent).map(node => ({ from: node.parent, to: node.key })) };
  const index = buildMindmapRelationIndex(graph, 'node-parent');
  const active = mindmapRunActiveKeys(nodes, 'active');
  assert.equal(active.length, 1000);
  assert.ok(active.every(key => key.startsWith('task-')));
  let visits = 0;
  const parents = { get(key) { visits++; return index.parents.get(key); } };
  const related = relatedMindmapNodes({ ...index, parents }, [...active, active[0], 'stale'], { ancestorsOnly: true });
  assert.equal(related.size, 1002);
  assert.equal(visits, 1002, 'shared parent paths are visited once across all executing seeds');
  assert.equal(related.has('idle'), false);
  assert.equal(related.has('plan-b'), false, 'executing PLAN is not a seed when TASKs are executing');
  nodes.filter(node => node.kind === 'task').forEach(node => { node.status = 'Pending'; });
  assert.deepEqual(mindmapRunActiveKeys(nodes, 'active'), ['plan-a', 'plan-b']);
  assert.deepEqual(sorted(relatedMindmapNodes(index, ['plan-a', 'plan-b'], { ancestorsOnly: true })), ['plan-a', 'plan-b', 'run']);
  assert.equal(mindmapRunActiveKeys(nodes, 'archived'), undefined);
  nodes.filter(node => node.kind === 'plan').forEach(node => { node.status = 'Finalized'; });
  assert.deepEqual(mindmapRunActiveKeys(nodes, 'active'), ['run']);
  assert.deepEqual(sorted(relatedMindmapNodes(index, ['run'], { ancestorsOnly: true })), ['run']);
  assert.equal(relatedMindmapNodes(index, [], { ancestorsOnly: true }), undefined);
});

test('duplicate edges, self edges and cycles terminate with the reachable nodes once', () => {
  const graph = graphOf(['a', 'b', 'c', 'other'],
    [['a', 'a'], ['a', 'b'], ['a', 'b'], ['b', 'c'], ['c', 'a']]);
  const index = buildMindmapRelationIndex(graph);
  assert.deepEqual(sorted(relatedMindmapNodes(index, 'b')), ['a', 'b', 'c']);
  graph.nodes[0].parent = 'b';
  graph.nodes[1].parent = 'a';
  assert.deepEqual(sorted(relatedMindmapNodes(buildMindmapRelationIndex(graph, 'node-parent'), 'a')), ['a', 'b', 'c']);
});

test('a cached index handles a long chain iteratively without rescanning graph edges', () => {
  const size = 30000;
  const graph = graphOf(Array.from({ length: size }, (_, i) => String(i)),
    Array.from({ length: size - 1 }, (_, i) => [String(i), String(i + 1)]));
  for (const value of [...graph.nodes, ...graph.edges]) Object.freeze(value);
  Object.freeze(graph.nodes);
  Object.freeze(graph.edges);
  const index = buildMindmapRelationIndex(graph);
  Object.defineProperty(graph, 'edges', { get() { throw new Error('edges must only be read during indexing'); } });
  assert.equal(relatedMindmapNodes(index, String(size / 2)).size, size);
  assert.equal(relatedMindmapNodes(index, '0').size, size);
});

test('indexed DAG results match the previous two-direction traversal for every active node', () => {
  const graph = graphOf(Array.from({ length: 37 }, (_, i) => String(i)),
    Array.from({ length: 37 }, (_, from) =>
      Array.from({ length: 37 - from - 1 }, (_, step) => [String(from), String(from + step + 1)]))
      .flat().filter(([from, to]) => (Number(from) * 7 + Number(to)) % 5 === 0));
  const index = buildMindmapRelationIndex(graph);
  for (const { key: active } of graph.nodes) {
    const expected = new Set([active]);
    for (const direction of ['from', 'to']) {
      const visited = new Set([active]), pending = [active];
      while (pending.length) {
        const key = pending.pop();
        for (const edge of graph.edges) {
          if (edge[direction] !== key) continue;
          const next = edge[direction === 'from' ? 'to' : 'from'];
          if (visited.has(next)) continue;
          visited.add(next); expected.add(next); pending.push(next);
        }
      }
    }
    assert.deepEqual(sorted(relatedMindmapNodes(index, active)), sorted(expected));
  }
});

function render(locale, component, props) {
  return renderToStaticMarkup(React.createElement(I18nProvider, { locale }, React.createElement(component, props)));
}
function attributeValues(html, attribute) {
  return [...html.matchAll(new RegExp(` ${attribute}="([^"]*)"`, 'g'))]
    .map(match => match[1].replaceAll('&quot;', '"').replaceAll('&#x27;', "'").replaceAll('&amp;', '&'));
}
function assertDomOrder(html, graph) {
  assert.deepEqual(attributeValues(html, 'data-mindmap-node'), graph.nodes.map(node => node.key));
  assert.equal((html.match(/class="wb-mm-edge"/g) ?? []).length, graph.edges.length);
  assert.equal((html.match(/class="wb-mm-pulse(?: wb-mm-flow)?"/g) ?? []).length, graph.edges.length);
  assert.equal((html.match(/class="wb-mm-pulse wb-mm-flow"/g) ?? []).length, graph.edges.filter(edge => edge.flowing).length);
}

test('memoized RUN cards keep all records, edge order, titles, focus targets and both locales', () => {
  const snapshot = {
    run: { id: 'run-1', source_db: '/foreign/tapl.db', request_summary: 'Run title', status: 'active' },
    plans: [{ id: 1, stable_id: 'PLAN-001', kind: 'plan', title: 'Plan title', status: 'In Progress' }],
    tasks: [{ id: 2, stable_id: 'TASK-001', kind: 'task', title: 'Task title', status: 'Completed', spec_id: 'PLAN-001' }]
  };
  const graph = buildRunMindmap(snapshot);
  for (const locale of ['en', 'ko']) {
    const html = render(locale, RunMindmap, { snapshot, open() {} });
    assertDomOrder(html, graph);
    assert.deepEqual(attributeValues(html, 'data-wb-focus'), ['plan:1', 'task:2', 'mindmap-follow']);
    assert.match(html, locale === 'en' ? /aria-label="Follow RUN and active work"/ : /aria-label="RUN과 진행 중인 작업 추적"/);
    assert.match(html, /Run title/);
    assert.match(html, /tabindex="0"/);
    assert.match(html, locale === 'en' ? /Completed/ : /완료/);
  }
});

test('memoized Memory cards preserve provenance attributes, unavailable sources and workspace/cue targets', () => {
  const memories = [{
    source_db: '/foreign/tapl.db', id: 'memory-1', note: 'Memory title', cue: ['Raw Cue'],
    state: 'active', revision: 2, source_available: false,
    source: { run_id: 'foreign-run', kind: 'item', item_id: 4, title: 'Source title' }
  }];
  const graph = buildMemoryMindmap(memories, { workspaceKey: '/current/tapl.db', workspaceTitle: 'tapl.db' });
  for (const locale of ['en', 'ko']) {
    const html = render(locale, MemoryMindmap, { memories, send() {}, cameraKey: 'memory', workspaceKey: '/current/tapl.db' });
    assertDomOrder(html, graph);
    assert.deepEqual(attributeValues(html, 'data-from'), graph.edges.map(edge => edge.from));
    assert.deepEqual(attributeValues(html, 'data-to'), graph.edges.map(edge => edge.to));
    assert.deepEqual(attributeValues(html, 'data-relation'), graph.edges.map(edge => edge.relation));
    assert.ok(attributeValues(html, 'data-wb-focus').includes('memory:/foreign/tapl.db:memory-1'));
    assert.match(html, /disabled=""/);
    assert.match(html, /Raw Cue/);
    assert.match(html, /aria-label="[^"]*tapl.db/);
  }
});

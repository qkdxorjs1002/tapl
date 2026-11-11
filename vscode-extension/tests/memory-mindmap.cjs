const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');

const filename = path.join(__dirname, 'memory-mindmap-render.cjs');
const output = buildSync({
  entryPoints: [path.join(__dirname, '../src/webview/workbench/memoryMindmapGraph.ts')],
  bundle: true, write: false, platform: 'node', format: 'cjs'
}).outputFiles[0].text;
const compiled = new Module(filename, module);
compiled.filename = filename;
compiled.paths = module.paths;
compiled._compile(output, filename);
const { buildMemoryMindmap } = compiled.exports;

function memory(id, overrides = {}) {
  return {
    source_db: '/one/tapl.db', id, note: `Memory ${id}`, cue: ['shared'],
    state: 'active', revision: 1,
    source: { run_id: 'run-1', kind: 'item', item_id: 1, archive_id: null, title: 'Source one' },
    created_at: '', updated_at: '', last_reinforced_at: null,
    half_life_days: 30, strength: 1, matched_cues: [], source_available: true,
    ...overrides
  };
}

function nodesOf(graph, kind) { return graph.nodes.filter(node => node.kind === kind); }
function freeze(value) {
  if (value && typeof value === 'object') {
    Object.freeze(value);
    Object.values(value).forEach(freeze);
  }
  return value;
}

function assertGraphGeometry(graph) {
  const lookup = new Map(graph.nodes.map(node => [node.key, node]));
  assert.equal(lookup.size, graph.nodes.length, 'every node has a unique key');
  assert.equal(new Set(graph.edges.map(edge => JSON.stringify(edge))).size, graph.edges.length, 'edges are unique');
  for (const edge of graph.edges) {
    const from = lookup.get(edge.from), to = lookup.get(edge.to);
    assert.ok(from && to, 'edges resolve to nodes');
    assert.ok(from.x + from.width / 2 < to.x - to.width / 2, 'edges advance left to right with a column gap');
    assert.equal(from.kind, edge.relation === 'source' ? 'source' : 'memory');
    assert.equal(to.kind, edge.relation === 'source' ? 'memory' : 'cue');
  }
  for (let a = 0; a < graph.nodes.length; a += 1) {
    const node = graph.nodes[a];
    assert.ok([node.x, node.y, node.width, node.height].every(Number.isFinite));
    assert.ok(node.x - node.width / 2 >= graph.bounds.minX - 1e-8);
    assert.ok(node.x + node.width / 2 <= graph.bounds.maxX + 1e-8);
    assert.ok(node.y - node.height / 2 >= graph.bounds.minY - 1e-8);
    assert.ok(node.y + node.height / 2 <= graph.bounds.maxY + 1e-8);
    for (let b = a + 1; b < graph.nodes.length; b += 1) {
      const other = graph.nodes[b];
      assert.ok(
        Math.abs(node.x - other.x) >= (node.width + other.width) / 2 ||
        Math.abs(node.y - other.y) >= (node.height + other.height) / 2,
        `${node.key} and ${other.key} do not overlap`
      );
    }
  }
  assert.ok(Math.abs(graph.bounds.minX + graph.bounds.maxX) < 1e-8);
  assert.ok(Math.abs(graph.bounds.minY + graph.bounds.maxY) < 1e-8);
}

test('shared sources and cues form actual multi-parent relationships with original object references', () => {
  const unavailable = memory('m1', { source_available: false });
  const available = memory('m2', { state: 'superseded', cue: ['shared', 'unique'] });
  const graph = buildMemoryMindmap([unavailable, available]);
  assert.equal(graph.memoryCount, 2);
  assert.equal(graph.sourceCount, 1);
  assert.equal(graph.cueCount, 2);
  const source = nodesOf(graph, 'source')[0];
  assert.equal(source.memory, available, 'source opening uses an available representative');
  assert.equal(source.count, 2);
  assert.equal(nodesOf(graph, 'memory')[0].memory, unavailable);
  assert.equal(nodesOf(graph, 'memory')[1].memory, available);
  assert.equal(nodesOf(graph, 'cue').find(node => node.cue === 'shared').count, 2);
  const children = graph.edges.filter(edge => edge.from === source.key).map(edge => graph.nodes.find(node => node.key === edge.to));
  assert.equal(source.y, (children[0].y + children[1].y) / 2);
  assert.equal(graph.edges.length, 5);
  assertGraphGeometry(graph);
});

test('database, run, kind and item identity prevent false provenance merges', () => {
  const inputs = [
    memory('same'),
    memory('same', { source_db: '/two/tapl.db' }),
    memory('m3', { source: { run_id: 'run-2', kind: 'item', item_id: 1 } }),
    memory('m4', { source: { run_id: 'run-1', kind: 'item', item_id: 2 } }),
    memory('m5', { source: { run_id: 'run-1', kind: 'run', item_id: null } }),
    memory('m6', { source: { run_id: 'run-1', kind: 'run', item_id: null, archive_id: 'other-archive' } })
  ];
  const graph = buildMemoryMindmap(inputs);
  assert.equal(graph.memoryCount, 6);
  assert.equal(graph.sourceCount, 5, 'archive metadata does not split the same original run');
  assert.equal(nodesOf(graph, 'memory').filter(node => node.memory.id === 'same').length, 2);
  assertGraphGeometry(graph);
});

test('cue identity uses NFKC, lowercase and folded whitespace while retaining raw text', () => {
  const raw = '  Ａ\tB\n';
  const graph = buildMemoryMindmap([
    memory('one', { cue: [raw, 'a b', '', ' \t\n', 'STRASSE', 'Straße'] }),
    memory('two', { cue: ['A   B', 'strasse', 'straße'], matched_cues: ['a b'] })
  ]);
  assert.equal(graph.cueCount, 3, 'lowercase does not pretend to implement Python casefold');
  const shared = nodesOf(graph, 'cue').find(node => node.cue === raw);
  assert.equal(shared.title, raw);
  assert.equal(shared.count, 2, 'duplicates inside one memory add only one relationship');
  assert.equal(shared.matched, true, 'matching cues retain emphasis after normalization and sharing');
  assert.equal(graph.edges.filter(edge => edge.to === shared.key).length, 2);
  assertGraphGeometry(graph);
});

test('missing and incomplete provenance never guesses shared sources', () => {
  const graph = buildMemoryMindmap([
    memory('missing', { source: undefined, cue: undefined }),
    memory('empty', { source: {}, cue: [] }),
    memory('no-db-one', { source_db: undefined }),
    memory('no-db-two', { source_db: undefined }),
    memory('partial-one', { source: { run_id: 'known', kind: 'item', item_id: null } }),
    memory('partial-two', { source: { run_id: 'known', kind: 'item', item_id: null } })
  ]);
  assert.equal(graph.memoryCount, 6);
  assert.equal(graph.sourceCount, 4);
  assert.ok(nodesOf(graph, 'source').every(node => node.count === 1));
  assertGraphGeometry(graph);
});

test('empty and deleted results stay empty; duplicate memory identities do not duplicate relationships', () => {
  const expected = { nodes: [], edges: [], bounds: { minX: 0, minY: 0, maxX: 0, maxY: 0 }, memoryCount: 0, sourceCount: 0, cueCount: 0 };
  assert.deepEqual(buildMemoryMindmap([]), expected);
  assert.deepEqual(buildMemoryMindmap([memory('gone', { state: 'deleted' })]), expected);
  const original = memory('same');
  const graph = buildMemoryMindmap([original, { ...original, note: 'Later duplicate' }]);
  assert.equal(graph.memoryCount, 1);
  assert.equal(nodesOf(graph, 'memory')[0].memory, original);
  assertGraphGeometry(graph);
});

test('hundreds of cards and dense shared cues remain deterministic, separated and immutable', () => {
  const inputs = freeze(Array.from({ length: 180 }, (_, index) => memory(`m${index}`, {
    source: { run_id: `run-${index % 13}`, kind: 'item', item_id: index % 13, title: `Source ${index % 13}` },
    cue: ['all', `shared-${index % 7}`, ...Array.from({ length: index % 11 }, (_, cue) => `unique-${index}-${cue}`)]
  })));
  const before = JSON.stringify(inputs);
  const graph = buildMemoryMindmap(inputs);
  assert.equal(graph.memoryCount, 180);
  assert.equal(graph.sourceCount, 13);
  assert.ok(graph.cueCount > 800);
  assertGraphGeometry(graph);
  assert.deepEqual(buildMemoryMindmap(inputs), graph);
  assert.equal(JSON.stringify(inputs), before);
  for (const node of nodesOf(graph, 'memory')) assert.ok(inputs.includes(node.memory));
  const cueNodes = nodesOf(graph, 'cue').sort((a, b) => a.y - b.y);
  const lookup = new Map(graph.nodes.map(node => [node.key, node]));
  let lastBarycenter = -Infinity;
  for (const cue of cueNodes) {
    const parents = graph.edges.filter(edge => edge.to === cue.key).map(edge => lookup.get(edge.from));
    const barycenter = parents.reduce((sum, node) => sum + node.y, 0) / parents.length;
    assert.ok(barycenter >= lastBarycenter - 1e-8, 'cue ordering follows connected memory barycenters');
    lastBarycenter = barycenter;
  }
});

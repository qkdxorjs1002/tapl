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
    if (edge.relation === 'workspace') {
      assert.equal(from.kind, 'workspace');
      assert.ok(to.kind === 'source' || to.kind === 'memory', 'collection links lead to actual result branches');
    } else {
      assert.equal(from.kind, edge.relation === 'source' ? 'source' : 'memory');
      assert.equal(to.kind, edge.relation === 'source' ? 'memory' : 'cue');
    }
    assert.ok(Math.hypot(to.x, to.y) > Math.hypot(from.x, from.y), 'branches advance outward from the workspace');
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
  assert.deepEqual(graph.bounds, {
    minX: Math.min(...graph.nodes.map(node => node.x - node.width / 2)),
    minY: Math.min(...graph.nodes.map(node => node.y - node.height / 2)),
    maxX: Math.max(...graph.nodes.map(node => node.x + node.width / 2)),
    maxY: Math.max(...graph.nodes.map(node => node.y + node.height / 2))
  }, 'bounds describe card edges without moving the workspace from the origin');
  const roots = nodesOf(graph, 'workspace');
  assert.equal(roots.length, 1);
  assert.equal(roots[0].x, 0);
  assert.equal(roots[0].y, 0);
  assert.equal(roots[0].count, graph.memoryCount);
  assert.equal(roots[0].memory, undefined, 'collection roots do not claim a source memory');
  assert.equal(graph.routing, 'radial');
}

test('the current workspace is a stable collection center, including results from connected databases', () => {
  const options = freeze({ workspaceKey: '/viewed/tapl.db', workspaceTitle: 'Current workspace' });
  const graph = buildMemoryMindmap([
    memory('local', { source_db: '/viewed/tapl.db' }),
    memory('foreign', { source_db: '/connected/tapl.db' }),
    memory('sourceless', { source: undefined, cue: [] })
  ], options);
  const root = nodesOf(graph, 'workspace')[0];
  assert.equal(root.title, options.workspaceTitle);
  assert.equal(root.key, JSON.stringify(['workspace', options.workspaceKey]));
  assert.equal(graph.sourceCount, 2, 'workspace collection links do not alter provenance counts');
  assert.equal(graph.edges.filter(edge => edge.relation === 'workspace').length, 3);
  assert.ok(graph.edges.some(edge => edge.from === root.key && edge.to === nodesOf(graph, 'memory').find(node => node.memory.id === 'sourceless').key));
  assert.equal(nodesOf(buildMemoryMindmap([memory('different')], options), 'workspace')[0].key, root.key, 'query results never determine workspace identity');
  const fallback = nodesOf(buildMemoryMindmap([memory('foreign', { source_db: '/foreign/tapl.db' })]), 'workspace')[0];
  assert.equal(fallback.title, 'Workspace');
  assert.equal(fallback.key, JSON.stringify(['workspace', null]), 'a foreign database does not become the viewing workspace');
  assertGraphGeometry(graph);
});

test('two source branches balance across the workspace and four occupy all cardinal directions', () => {
  for (const count of [2, 4]) {
    const graph = buildMemoryMindmap(Array.from({ length: count }, (_, index) => memory(`m${index}`, {
      source: { run_id: `run-${index}`, kind: 'item', item_id: index, title: `Source ${index}` },
      cue: [`cue-${index}`]
    })));
    const sources = nodesOf(graph, 'source');
    assert.ok(sources.every(node => Math.abs(Math.hypot(node.x, node.y) - 340) < 1e-8), 'sparse branches start near the workspace');
    assert.ok(sources.some(node => node.x > 0 && node.y === 0));
    assert.ok(sources.some(node => node.x < 0 && node.y === 0));
    if (count === 4) {
      assert.ok(sources.some(node => node.x === 0 && node.y > 0));
      assert.ok(sources.some(node => node.x === 0 && node.y < 0));
    }
    assertGraphGeometry(graph);
  }
});

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
  assert.equal(graph.edges.filter(edge => edge.relation === 'source').length, 2);
  assert.equal(graph.edges.length, 6);
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
  const same = nodesOf(graph, 'memory').filter(node => node.memory.id === 'same');
  assert.notEqual(same[0].key, same[1].key);
  const sourceParents = same.map(node => graph.edges.find(edge => edge.relation === 'source' && edge.to === node.key).from);
  assert.notEqual(sourceParents[0], sourceParents[1]);
  assert.ok(graph.edges.every(edge => ['workspace', 'source', 'cue'].includes(edge.relation)), 'no semantic, replacement, or cross-database ownership edges are inferred');
  assertGraphGeometry(graph);
});

test('a normalized cue shared across sectors remains one node with only its actual parents', () => {
  const inputs = Array.from({ length: 4 }, (_, index) => memory(`m${index}`, {
    source_db: index === 2 ? '/foreign/tapl.db' : '/one/tapl.db',
    source: { run_id: `run-${index}`, kind: 'item', item_id: index },
    cue: index === 0 ? [' Shared  Cue '] : index === 2 ? ['ＳＨＡＲＥＤ cue'] : [`other-${index}`],
    note: index === 1 ? 'm0 replaces m2 and references run-0' : `Memory ${index}`,
    state: index === 2 ? 'superseded' : 'active'
  }));
  const graph = buildMemoryMindmap(inputs);
  const shared = nodesOf(graph, 'cue').find(node => node.cue === ' Shared  Cue ');
  assert.equal(shared.count, 2);
  const parents = graph.edges.filter(edge => edge.to === shared.key).map(edge => graph.nodes.find(node => node.key === edge.from));
  assert.deepEqual(parents.map(node => node.memory), [inputs[0], inputs[2]]);
  assert.ok(parents[0].x > 0 && parents[1].x < 0, 'real parents span opposite source sectors');
  assert.equal(graph.edges.filter(edge => edge.relation === 'source').length, 4);
  assert.equal(graph.edges.filter(edge => edge.relation === 'workspace').length, 4);
  assert.equal(graph.edges.filter(edge => edge.relation === 'cue').length, 4);
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
  const directMemories = graph.edges.filter(edge => edge.relation === 'workspace').map(edge => graph.nodes.find(node => node.key === edge.to)).filter(node => node.kind === 'memory');
  assert.deepEqual(directMemories.map(node => node.memory.id), ['missing', 'empty']);
  assertGraphGeometry(graph);
});

test('empty and deleted results stay empty; duplicate memory identities do not duplicate relationships', () => {
  const expected = { nodes: [], edges: [], bounds: { minX: 0, minY: 0, maxX: 0, maxY: 0 }, memoryCount: 0, sourceCount: 0, cueCount: 0, routing: 'radial' };
  assert.deepEqual(buildMemoryMindmap([]), expected);
  assert.deepEqual(buildMemoryMindmap([memory('gone', { state: 'deleted' })]), expected);
  assert.deepEqual(buildMemoryMindmap([], { workspaceKey: 'configured', workspaceTitle: 'No results' }), expected);
  const original = memory('same');
  const graph = buildMemoryMindmap([original, { ...original, note: 'Later duplicate' }]);
  assert.equal(graph.memoryCount, 1);
  assert.equal(nodesOf(graph, 'memory')[0].memory, original);
  assertGraphGeometry(graph);
});

test('a fifty-memory page with forty-seven sources keeps nearby anchors without overlapping cards', () => {
  const graph = buildMemoryMindmap(Array.from({ length: 50 }, (_, index) => memory(`m${index}`, {
    source: { run_id: `run-${index % 47}`, kind: 'item', item_id: index % 47, title: `Source ${index % 47}` },
    cue: [`cue-${index}`]
  })));
  assert.equal(graph.sourceCount, 47);
  const radii = nodesOf(graph, 'source').map(node => Math.hypot(node.x, node.y));
  assert.ok(radii.filter(radius => radius < 400).length >= 4, 'several first branches stay near the viewing origin');
  assert.ok(Math.max(...radii) < 1800, 'source packing does not reserve a distant ring for all branches');
  assertGraphGeometry(graph);
});

test('hundreds of cards and dense shared cues remain deterministic, separated and immutable', () => {
  const inputs = freeze(Array.from({ length: 196 }, (_, index) => memory(`m${index}`, {
    source: { run_id: `run-${index % 13}`, kind: 'item', item_id: index % 13, title: `Source ${index % 13}` },
    cue: ['all', `shared-${index % 7}`, ...Array.from({ length: index % 11 }, (_, cue) => `unique-${index}-${cue}`)]
  })));
  const before = JSON.stringify(inputs);
  const graph = buildMemoryMindmap(inputs);
  assert.equal(graph.memoryCount, 196);
  assert.equal(graph.sourceCount, 13);
  assert.ok(graph.cueCount > 800);
  assertGraphGeometry(graph);
  assert.deepEqual(buildMemoryMindmap(inputs), graph);
  assert.equal(JSON.stringify(inputs), before);
  for (const node of nodesOf(graph, 'memory')) assert.ok(inputs.includes(node.memory));
  const all = nodesOf(graph, 'cue').find(node => node.cue === 'all');
  assert.equal(all.count, inputs.length);
  assert.equal(graph.edges.filter(edge => edge.to === all.key).length, inputs.length, 'a cue spanning every sector retains all real parents');
  assert.ok(nodesOf(graph, 'source').some(node => node.x < 0));
  assert.ok(nodesOf(graph, 'source').some(node => node.y < 0));
});

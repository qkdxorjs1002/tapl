const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { buildSync } = require('esbuild');

const output = buildSync({
  stdin: { contents: "export * from './mindmap'; export * from './mindmapCamera';", resolveDir: path.join(__dirname, '../src/webview/workbench') },
  bundle: true, platform: 'node', format: 'cjs', write: false
}).outputFiles[0].text;
const compiled = { exports: {} };
new Function('module', 'exports', output)(compiled, compiled.exports);
const { buildRunMindmap, constrainMindmapCamera, mindmapMinimumZoom } = compiled.exports;
const run = { id: 'run-1', source_db: 'main.sqlite3', request_summary: 'The actual user request', status: 'active' };
const snapshot = (plans = [], tasks = [], selected = run) => ({
  run: selected, plans, tasks, findings: [], task_counts: { Completed: 900 },
  active_batches: [], active_executions: [], readonly: false
});
const plan = (id, extra = {}) => ({ id, stable_id: `PLAN-${id}`, kind: 'plan', title: `Plan ${id}`, ...extra });
const task = (id, extra = {}) => ({ id, stable_id: `TASK-${id}`, kind: 'task', title: `Task ${id}`, status: 'Pending', ...extra });
const nodeFor = (graph, item) => graph.nodes.find((node) => node.item === item);
const rootFor = (graph) => graph.nodes.find((node) => node.kind === 'run');

function assertNoOverlap(graph) {
  for (let a = 0; a < graph.nodes.length; a += 1) {
    const first = graph.nodes[a];
    assert.ok(Number.isFinite(first.x) && Number.isFinite(first.y), `${first.key} has finite coordinates`);
    assert.ok(first.x - first.width / 2 >= graph.bounds.minX);
    assert.ok(first.x + first.width / 2 <= graph.bounds.maxX);
    assert.ok(first.y - first.height / 2 >= graph.bounds.minY);
    assert.ok(first.y + first.height / 2 <= graph.bounds.maxY);
    for (let b = a + 1; b < graph.nodes.length; b += 1) {
      const second = graph.nodes[b];
      assert.ok(
        Math.abs(first.x - second.x) >= (first.width + second.width) / 2
        || Math.abs(first.y - second.y) >= (first.height + second.height) / 2,
        `overlap: ${first.key} and ${second.key}`
      );
    }
  }
}

test('RUN title and all TASK statuses use actual records; PLAN progress uses direct children', () => {
  const first = plan(1);
  const empty = plan(2, { status: 'Completed' });
  const tasks = ['Completed', 'In Progress', 'Blocked', 'Pending', 'Skipped', 'Custom'].map((status, i) =>
    task(i + 1, { status, spec_id: first.stable_id }));
  const graph = buildRunMindmap(snapshot([first, empty], tasks));
  const root = rootFor(graph);
  assert.equal(root.title, run.request_summary);
  assert.equal(root.parent, undefined);
  assert.deepEqual([graph.completed, graph.total, graph.percent], [1, 6, 17]);
  assert.deepEqual([root.completed, root.total], [1, 6]);
  assert.deepEqual([nodeFor(graph, first).completed, nodeFor(graph, first).total], [1, 6]);
  assert.deepEqual([nodeFor(graph, empty).completed, nodeFor(graph, empty).total], [0, 0]);
  assert.equal(graph.nodes.filter((node) => node.kind === 'task').length, tasks.length);
  for (const item of tasks) assert.equal(nodeFor(graph, item).parent, nodeFor(graph, first).key);
  assert.equal(graph.edges.length, graph.nodes.length - 1);
});

test('missing, unknown and ambiguous PLAN relationships connect directly to RUN without fake plans', () => {
  const first = plan(1);
  const duplicate = plan(2, { stable_id: first.stable_id });
  const tasks = [task(1), task(2, { spec_id: 'missing' }), task(3, { spec_id: first.stable_id })];
  const graph = buildRunMindmap(snapshot([first, duplicate], tasks));
  assert.equal(graph.nodes.filter((node) => node.kind === 'plan').length, 2);
  for (const item of tasks) assert.equal(nodeFor(graph, item).parent, rootFor(graph).key);
  assertNoOverlap(graph);
});

test('flow follows executing items and their ancestors without lighting idle siblings or ended RUNs', () => {
  const first = plan(1, { status: 'Finalized' });
  const idle = plan(2, { status: 'Finalized' });
  const workingPlan = plan(3, { status: 'In Progress' });
  const tasks = ['In Progress', 'Pending', 'Completed', 'Blocked', 'Skipped', 'active'].map((status, i) =>
    task(i + 1, { status, spec_id: first.stable_id }));
  const orphan = task(10, { status: 'In Progress' });
  const graph = buildRunMindmap(snapshot([first, idle, workingPlan], [...tasks, orphan]));
  const flowing = graph.edges.filter(edge => edge.flowing).map(edge => edge.to).sort();
  assert.deepEqual(flowing, [first, workingPlan, tasks[0], orphan].map(item => nodeFor(graph, item).key).sort());
  assert.deepEqual(buildRunMindmap(snapshot([idle], [task(20)])).edges.map(edge => edge.flowing), [false, false], 'an active RUN alone does not animate');
  for (const status of ['archived', 'completed', 'queued']) {
    const ended = buildRunMindmap(snapshot([first, workingPlan], [...tasks, orphan], { ...run, status }));
    assert.ok(ended.edges.every(edge => !edge.flowing), `${status}: stale executing records stay static`);
  }
  tasks[0].status = 'Completed';
  orphan.status = 'Blocked';
  workingPlan.status = 'Finalized';
  assert.ok(buildRunMindmap(snapshot([first, idle, workingPlan], [...tasks, orphan])).edges.every(edge => !edge.flowing), 'status refresh removes the whole completed path');
});

test('explicit foreign sources and RUNs cannot attach or contribute to the selected RUN', () => {
  const localPlan = plan(1);
  const foreignSourcePlan = plan(2, { source_db: 'peer.sqlite3' });
  const foreignRunPlan = plan(3, { run_id: 'other-run' });
  const localTask = task(1, { spec_id: localPlan.stable_id, status: 'Completed' });
  const foreignSourceTask = task(2, { source_db: 'peer.sqlite3', spec_id: localPlan.stable_id, status: 'Completed' });
  const foreignRunTask = task(3, { run_id: 'other-run', spec_id: localPlan.stable_id, status: 'Completed' });
  const orphan = task(4, { spec_id: foreignSourcePlan.stable_id });
  const graph = buildRunMindmap(snapshot([localPlan, foreignSourcePlan, foreignRunPlan], [localTask, foreignSourceTask, foreignRunTask, orphan]));
  assert.equal(graph.nodes.length, 4);
  for (const foreign of [foreignSourcePlan, foreignRunPlan, foreignSourceTask, foreignRunTask]) assert.equal(nodeFor(graph, foreign), undefined);
  assert.equal(nodeFor(graph, localTask).parent, nodeFor(graph, localPlan).key);
  assert.equal(nodeFor(graph, orphan).parent, rootFor(graph).key);
  assert.deepEqual([graph.completed, graph.total, graph.percent], [1, 2, 50]);
});

test('node keys preserve database/RUN identity and tuple boundaries; records retain original references', () => {
  const item = Object.freeze(task(1, { spec_id: 'PLAN-1' }));
  const parent = Object.freeze(plan(1));
  const data = snapshot(Object.freeze([parent]), Object.freeze([item]));
  const graph = buildRunMindmap(Object.freeze(data));
  assert.equal(nodeFor(graph, item).item, item);
  assert.equal(nodeFor(graph, parent).item, parent);
  const peer = buildRunMindmap(snapshot([parent], [item], { ...run, source_db: 'peer.sqlite3' }));
  const otherRun = buildRunMindmap(snapshot([parent], [item], { ...run, id: 'run-2' }));
  for (const other of [peer, otherRun]) {
    assert.ok(graph.nodes.every((node) => !other.nodes.some((candidate) => candidate.key === node.key)));
  }
  const first = buildRunMindmap(snapshot([], [item], { source_db: 'a|b', id: 'c' }));
  const second = buildRunMindmap(snapshot([], [item], { source_db: 'a', id: 'b|c' }));
  assert.notEqual(rootFor(first).key, rootFor(second).key);
  assert.notEqual(nodeFor(first, item).key, nodeFor(second, item).key);
});

test('empty, PLAN-only and TASK-only snapshots remain finite with zero-safe completion', () => {
  for (const data of [snapshot(), snapshot([plan(1), plan(2)]), snapshot([], Array.from({ length: 35 }, (_, i) => task(i)))]) {
    const graph = buildRunMindmap(data);
    assertNoOverlap(graph);
    assert.equal(graph.percent, 0);
    assert.equal(graph.completed, 0);
    assert.equal(graph.total, data.tasks.length);
    assert.equal(graph.edges.length, graph.nodes.length - 1);
  }
  assert.deepEqual(buildRunMindmap(snapshot()).bounds, { minX: -119, minY: -79, maxX: 119, maxY: 79 });
});

test('hundreds of mixed branches avoid overlaps, balance lanes and stay deterministic across polling order', () => {
  const plans = Array.from({ length: 24 }, (_, i) => plan(i + 1));
  const tasks = Array.from({ length: 540 }, (_, i) => task(i + 1, {
    spec_id: i % 7 ? plans[i % plans.length].stable_id : undefined,
    status: i % 3 === 0 ? 'Completed' : 'Pending'
  }));
  const graph = buildRunMindmap(snapshot(plans, tasks));
  const reordered = buildRunMindmap(snapshot([...plans].reverse(), [...tasks].reverse()));
  assertNoOverlap(graph);
  assert.deepEqual(graph, reordered);
  assert.equal(graph.nodes.length, 565);
  assert.equal(new Set(graph.nodes.map((node) => node.key)).size, graph.nodes.length);
  assert.deepEqual([graph.completed, graph.total, graph.percent], [180, 540, 33]);
  const laneHeight = (side) => {
    const nodes = graph.nodes.filter((node) => Math.sign(node.x) === side);
    return Math.max(...nodes.map((node) => node.y + node.height / 2)) - Math.min(...nodes.map((node) => node.y - node.height / 2));
  };
  assert.ok(Math.abs(laneHeight(-1) - laneHeight(1)) < 300);
});

test('a large single PLAN and many unparented TASKs reserve their full subtree heights', () => {
  const first = plan(1);
  const tasks = Array.from({ length: 180 }, (_, i) => task(i + 1, { spec_id: i < 130 ? first.stable_id : undefined }));
  const graph = buildRunMindmap(snapshot([first], tasks));
  assertNoOverlap(graph);
  const children = graph.nodes.filter((node) => node.parent === nodeFor(graph, first).key);
  assert.equal(children.length, 130);
  for (let i = 1; i < children.length; i += 1) assert.equal(children[i].y - children[i - 1].y, 88);
});

test('numeric stable-ID variants have deterministic order and duplicate record tuples keep unique keys', () => {
  const tasks = [task(1), task(1, { stable_id: 'TASK-01' }), task(2, { stable_id: 'TASK-1' })];
  const graph = buildRunMindmap(snapshot([], tasks));
  assert.deepEqual(graph, buildRunMindmap(snapshot([], [...tasks].reverse())));
  const duplicates = buildRunMindmap(snapshot([], [tasks[0], tasks[0]]));
  assert.equal(new Set(duplicates.nodes.map((node) => node.key)).size, 3);
  assert.equal(duplicates.total, 2);
});

test('camera stays near the graph at extreme pan and re-clamps after zoom or viewport changes', () => {
  const graph = buildRunMindmap(snapshot([plan(1)], Array.from({ length: 30 }, (_, i) => task(i, { spec_id: 'PLAN-1' }))));
  for (const viewport of [{ width: 390, height: 780 }, { width: 1368, height: 928 }]) {
    for (const zoom of [.01, .72, 2.8]) {
      for (const direction of [-1, 1]) {
        const result = constrainMindmapCamera({ x: direction * 1e7, y: direction * 1e7, zoom }, graph.bounds, viewport);
        assert.ok(Math.abs(result.x) < 1e4 && Math.abs(result.y) < 1e4, 'no unbounded empty-space travel');
        assert.ok(result.zoom >= mindmapMinimumZoom(graph.bounds, viewport));
        const right = graph.bounds.maxX * result.zoom + result.x;
        const left = graph.bounds.minX * result.zoom + result.x;
        const bottom = graph.bounds.maxY * result.zoom + result.y;
        const top = graph.bounds.minY * result.zoom + result.y;
        assert.ok(right > -viewport.width / 2 && left < viewport.width / 2, 'graph remains horizontally visible');
        assert.ok(bottom > -viewport.height / 2 && top < viewport.height / 2, 'graph remains vertically visible');
        assert.deepEqual(constrainMindmapCamera(result, graph.bounds, viewport), result, 'constraint is stable');
      }
    }
    const center = constrainMindmapCamera({ x: 0, y: 0, zoom: .72 }, graph.bounds, viewport);
    assert.equal(center.x, 0); assert.equal(center.y, 0);
  }
  const onlyRun = buildRunMindmap(snapshot());
  const camera = constrainMindmapCamera({ x: 10000, y: -10000, zoom: .001 }, onlyRun.bounds, { width: 1368, height: 928 });
  assert.equal(camera.zoom, .72, 'empty RUN cannot be zoomed into an unreadable dot');
  assert.ok(Math.abs(camera.x) <= 96 && Math.abs(camera.y) <= 96);
});

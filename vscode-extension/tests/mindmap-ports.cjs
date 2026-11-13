const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { buildSync } = require('esbuild');
const output = buildSync({
  stdin: { contents: "export * from './mindmapGeometry'; export * from './mindmapPorts';", resolveDir: path.join(__dirname, '../src/webview/workbench') },
  bundle: true, platform: 'node', format: 'cjs', write: false
}).outputFiles[0].text;
const compiled = { exports: {} };
new Function('module', 'exports', output)(compiled, compiled.exports);
const { mindmapEdgeAttachments: allocate, mindmapConnectionGeometry: connect } = compiled.exports;
const node = (key, x, y, width = 216, height = 100) => ({ key, x, y, width, height });
const hub = node('hub', 0, 0);
const tasks = [-132, -44, 44, 132].map((y, i) => node(`task-${i}`, 300, y, 210, 66));
const edgesFor = targets => targets.map(target => ({ from: 'hub', to: target.key }));
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);
const geometry = (nodes, edges, slots) => {
  const byKey = new Map(nodes.map(n => [n.key, n]));
  return edges.map((edge, i) => connect(byKey.get(edge.from), byKey.get(edge.to), 'radial', undefined, undefined, slots[i]));
};

test('four PLAN lines occupy four equally spaced points across its central 35%', () => {
  const nodes = [hub, ...tasks], edges = edgesFor(tasks), slots = allocate(nodes, edges, 'radial');
  const curves = geometry(nodes, edges, slots);
  assert.equal(new Set(curves.map(c => c.start.y)).size, 4);
  curves.forEach((curve, i) => {
    close(curve.start.y, -17.5 + i * 35 / 3);
    close(curve.start.x, 108); assert.equal(curve.fromSide, 'right');
    assert.equal(slots[i].to, undefined, 'single TASK endpoint retains its projection');
  });
});

test('single and explicit horizontal connections preserve their existing geometry', () => {
  const edges = edgesFor(tasks.slice(0, 1)), slots = allocate([hub, tasks[0]], edges, 'radial');
  assert.equal(slots[0], undefined);
  assert.deepEqual(geometry([hub, tasks[0]], edges, slots)[0], connect(hub, tasks[0], 'radial'));
  assert.deepEqual(Array.from(allocate([hub, ...tasks], edgesFor(tasks), 'horizontal')), [undefined, undefined, undefined, undefined]);
  assert.deepEqual(connect(hub, tasks[0], 'horizontal', undefined, undefined, { from: { side: 'right', offset: .175 } }), connect(hub, tasks[0], 'horizontal'));
});

test('left, right, top and bottom fans retain world-coordinate ordering', () => {
  for (const horizontal of [true, false]) for (const sign of [-1, 1]) {
    const targets = [-132, -44, 44, 132].map((p, i) => node(`target-${i}`, horizontal ? sign * 300 : p, horizontal ? p : sign * 300, 210, 66));
    const nodes = [hub, ...targets], edges = edgesFor(targets), curves = geometry(nodes, edges, allocate(nodes, edges, 'radial'));
    curves.forEach((curve, i) => {
      close(horizontal ? curve.start.y : curve.start.x, (horizontal ? hub.height : hub.width) * (-.175 + i * .35 / 3));
      close(horizontal ? curve.start.x : curve.start.y, sign * (horizontal ? hub.width : hub.height) / 2);
    });
  }
});

test('incoming and outgoing ends share a side group, and reversed edges keep their slots', () => {
  const nodes = [hub, ...tasks], edges = tasks.map((target, i) => i % 2 ? { from: target.key, to: 'hub' } : { from: 'hub', to: target.key });
  const curves = geometry(nodes, edges, allocate(nodes, edges, 'radial'));
  const reversed = edges.map(edge => ({ from: edge.to, to: edge.from }));
  const reverseCurves = geometry(nodes, reversed, allocate(nodes, reversed, 'radial'));
  curves.forEach((curve, i) => {
    close((i % 2 ? curve.end : curve.start).y, -17.5 + i * 35 / 3);
    assert.deepEqual(curve.start, reverseCurves[i].end);
    assert.deepEqual(curve.end, reverseCurves[i].start);
    assert.deepEqual(curve.control1, reverseCurves[i].control2);
  });
});

test('equal coordinates use stable opposite keys across node and edge reordering', () => {
  const a = node('a', 300, 0), b = node('b', 500, 0), edges = edgesFor([a, b]);
  const first = allocate([hub, a, b], edges, 'radial'), next = allocate([b, a, hub], [...edges].reverse(), 'radial');
  close(first[0].from.offset, -.175); close(first[1].from.offset, .175);
  close(next[1].from.offset, first[0].from.offset); close(next[0].from.offset, first[1].from.offset);
});

test('magnetic motion retains allocated spacing on the displaced side', () => {
  const nodes = [hub, ...tasks], edges = edgesFor(tasks), slots = allocate(nodes, edges, 'radial');
  for (const offset of [{ x: 2, y: -3 }, { x: -3, y: 1 }]) {
    const curves = tasks.map((target, i) => connect(hub, target, 'radial', offset, { x: i - 2, y: 2 - i }, slots[i]));
    assert.equal(new Set(curves.map(c => c.start.y)).size, 4);
    curves.forEach((curve, i) => { close(curve.start.y, offset.y + 100 * slots[i].from.offset); close(curve.start.x, offset.x + 108); });
  }
});

test('stale sides and invalid slots cannot force an unsafe corridor or escape the band', () => {
  const target = node('near', 213.5, 132, 210, 66);
  const old = { from: { side: 'right', offset: -.175 }, to: { side: 'left', offset: .175 } };
  const moved = connect(hub, target, 'radial', { x: 3, y: 0 }, { x: -3, y: 0 }, old);
  assert.equal(moved.fromSide, 'bottom');
  assert.deepEqual(moved, connect(hub, target, 'radial', { x: 3, y: 0 }, { x: -3, y: 0 }));
  close(connect(hub, tasks[0], 'radial', undefined, undefined, { from: { side: 'right', offset: 8 } }).start.y, 17.5);
  assert.deepEqual(connect(hub, tasks[0], 'radial', undefined, undefined, { from: { side: 'right', offset: NaN } }), connect(hub, tasks[0], 'radial'));
});

test('missing nodes, duplicate edges and zero-size nodes remain bounded and finite', () => {
  const nodes = [node('hub', 0, 0, 0, 0), node('a', 300, 0, 0, 0)];
  const edges = [{ from: 'hub', to: 'a' }, { from: 'hub', to: 'a' }, { from: 'missing', to: 'a' }];
  const slots = allocate(nodes, edges, 'radial');
  assert.equal(slots.length, 3); assert.equal(slots[2], undefined);
  for (const curve of geometry(nodes, edges.slice(0, 2), slots)) assert.doesNotMatch(curve.path, /NaN|Infinity/);
  assert.equal(allocate([], [], 'radial').length, 0);
});

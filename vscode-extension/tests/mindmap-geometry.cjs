const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { buildSync } = require('esbuild');

const output = buildSync({
  entryPoints: [path.join(__dirname, '../src/webview/workbench/mindmapGeometry.ts')],
  bundle: true, platform: 'node', format: 'cjs', write: false
}).outputFiles[0].text;
const compiled = { exports: {} };
new Function('module', 'exports', output)(compiled, compiled.exports);
const { mindmapConnectionGeometry: connect, mindmapConnectionPoint: pointAt } = compiled.exports;
const node = (x, y, width = 120, height = 80) => ({ x, y, width, height });
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} != ${expected}`);
const closePoint = (actual, expected) => { close(actual.x, expected.x); close(actual.y, expected.y); };
function assertBoundary(point, rectangle) {
  const dx = Math.abs(point.x - rectangle.x), dy = Math.abs(point.y - rectangle.y);
  assert.ok(dx <= rectangle.width / 2 + 1e-9 && dy <= rectangle.height / 2 + 1e-9, 'anchor is inside rectangle extents');
  assert.ok(Math.abs(dx - rectangle.width / 2) < 1e-9 || Math.abs(dy - rectangle.height / 2) < 1e-9, 'anchor lies on rectangle boundary');
  assert.ok((Math.abs(dx - rectangle.width / 2) < 1e-9 && dy < 1e-9)
    || (Math.abs(dy - rectangle.height / 2) < 1e-9 && dx < 1e-9), 'anchor is one of the four side midpoints');
}

test('horizontal compatibility mode preserves anchors, midpoint controls and exact SVG paths', () => {
  const from = node(-200, 0, 100, 60), to = node(0, -80, 100, 60);
  assert.deepEqual(connect(from, to), {
    start: { x: -150, y: 0 }, end: { x: -50, y: -80 }, middle: -100,
    control1: { x: -100, y: 0 }, control2: { x: -100, y: -80 },
    path: 'M -150 0 C -100 0, -100 -80, -50 -80'
  });
  assert.equal(connect(to, from).path, 'M -50 -80 C -100 -80, -100 0, -150 0');
  assert.equal(connect(node(0, -100), node(0, 100)).path, 'M 60 -100 C 0 -100, 0 100, -60 100');
  assert.deepEqual(connect(from, to, 'horizontal'), connect(from, to));
});

test('radial anchors select only side midpoints in all quadrants and axes', () => {
  const from = node(0, 0);
  for (const [dx, dy] of [[300, 400], [-300, 400], [-300, -400], [300, -400], [600, 80], [-600, 80], [0, 400], [0, -400], [400, 0], [-400, 0]]) {
    const to = node(dx, dy, 80, 100);
    const geometry = connect(from, to, 'radial');
    assertBoundary(geometry.start, from);
    assertBoundary(geometry.end, to);
    assert.ok(geometry.start.x * dx + geometry.start.y * dy > 0, 'source anchor faces target');
    assert.ok((geometry.end.x - dx) * dx + (geometry.end.y - dy) * dy < 0, 'target anchor faces source');
  }
  closePoint(connect(from, node(300, 400, 80, 100), 'radial').start, { x: 0, y: 40 });
});

test('radial controls leave the correct side and reverse with the connection orientation', () => {
  const from = node(0, 0);
  for (const to of [node(0, 400), node(0, -400), node(600, 80), node(-600, -80), node(300, 400, 80, 100)]) {
    const forward = connect(from, to, 'radial'), reverse = connect(to, from, 'radial');
    closePoint(forward.start, reverse.end);
    closePoint(forward.end, reverse.start);
    closePoint(forward.control1, reverse.control2);
    closePoint(forward.control2, reverse.control1);
    const dx = to.x - from.x, dy = to.y - from.y;
    assert.ok((forward.control1.x - forward.start.x) * dx + (forward.control1.y - forward.start.y) * dy > 0);
    assert.ok((forward.control2.x - forward.end.x) * dx + (forward.control2.y - forward.end.y) * dy < 0);
    closePoint(pointAt(forward, 0.23), pointAt(reverse, 0.77));
  }
  const vertical = connect(from, node(0, 400), 'radial');
  assert.equal(vertical.control1.x, 0);
  assert.equal(vertical.control2.x, 0);
  assert.ok(vertical.control1.y > vertical.start.y && vertical.control2.y < vertical.end.y);
});

test('coincident centers, overlapping rectangles and zero dimensions remain stable and finite', () => {
  for (const [from, to] of [
    [node(0, 0), node(0, 0)], [node(0, 0), node(10, 10)],
    [node(0, 0, 0, 0), node(0, 0, 0, 0)], [node(0, 0, 0, 0), node(0, 100, 0, 80)],
    [node(0, 0, 100, 0), node(100, 0, 0, 0)]
  ]) {
    const geometry = connect(from, to, 'radial');
    assert.deepEqual(geometry, connect(from, to, 'radial'));
    assertBoundary(geometry.start, from);
    assertBoundary(geometry.end, to);
    for (const point of [geometry.start, geometry.end, geometry.control1, geometry.control2, ...[0, .25, .5, .75, 1].map((p) => pointAt(geometry, p))]) {
      assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y));
    }
    assert.doesNotMatch(geometry.path, /NaN|Infinity/);
  }
});

test('independent motion offsets reroute radial anchors on displaced rectangles and pulses follow that cubic', () => {
  const from = node(0, 0), to = node(300, 400, 80, 100);
  const fromOffset = { x: 3, y: -2 }, toOffset = { x: -2, y: 3 };
  const movedFrom = { ...from, x: 3, y: -2 }, movedTo = { ...to, x: 298, y: 403 };
  const moved = connect(from, to, 'radial', fromOffset, toOffset);
  assert.deepEqual(moved, connect(movedFrom, movedTo, 'radial'));
  assertBoundary(moved.start, movedFrom);
  assertBoundary(moved.end, movedTo);
  closePoint(moved.start, { x: 3, y: 38 });
  closePoint(pointAt(moved, 0), moved.start);
  closePoint(pointAt(moved, 1), moved.end);
  closePoint(pointAt(moved, .5), {
    x: (moved.start.x + 3 * moved.control1.x + 3 * moved.control2.x + moved.end.x) / 8,
    y: (moved.start.y + 3 * moved.control1.y + 3 * moved.control2.y + moved.end.y) / 8
  });
  assert.equal(connect(from, to, 'horizontal', fromOffset, toOffset).path, 'M 63 -2 C 160.5 -2, 160.5 403, 258 403');
});

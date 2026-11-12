const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { buildSync } = require('esbuild');

const output = buildSync({
  entryPoints: [path.join(__dirname, '../src/webview/workbench/mindmapMotion.ts')],
  bundle: true, platform: 'node', format: 'cjs', write: false
}).outputFiles[0].text;
const compiled = { exports: {} };
new Function('module', 'exports', output)(compiled, compiled.exports);
const {
  mindmapWorldView: viewAt, mindmapConnectionBounds: boundsOf, mindmapIntersects: intersects,
  mindmapVisiblePulses: pulsesFor, mindmapNearbyNodes: nearbyNodes, mindmapMagneticOffset: offsetFor,
  mindmapPulseLookup: pulseLookup,
  MINDMAP_PULSE_LIMIT: pulseLimit, MINDMAP_DECORATION_INTERVAL: decorationInterval
} = compiled.exports;

test('world visibility uses centered camera coordinates and screen-space margins at every zoom', () => {
  assert.deepEqual(viewAt({ x: 100, y: -50, zoom: 2 }, { width: 800, height: 600 }),
    { left: -250, right: 150, top: -125, bottom: 175 });
  assert.deepEqual(viewAt({ x: 100, y: -50, zoom: .5 }, { width: 800, height: 600 }, 10),
    { left: -1020, right: 620, top: -520, bottom: 720 });
});

test('pulse culling retains crossing curves with offscreen endpoints and bounds total animation', () => {
  const view = { left: -10, right: 10, top: -10, bottom: 10 };
  const crossing = boundsOf({ start: { x: -100, y: 100 }, end: { x: 100, y: 100 },
    control1: { x: -50, y: -100 }, control2: { x: 50, y: -100 } });
  assert.ok(intersects(crossing, view), 'control hull includes visible interior of curve');
  const offscreen = { left: 1000, right: 1100, top: 1000, bottom: 1100 };
  assert.deepEqual(pulsesFor([offscreen, crossing, offscreen], view), [1]);
  const large = Array.from({ length: 1040 }, (_, index) => index % 2 ? crossing : offscreen);
  const selected = pulsesFor(large, view);
  assert.equal(selected.length, pulseLimit);
  assert.equal(new Set(selected).size, pulseLimit);
  assert.ok(selected.every((index) => index % 2 === 1));
  assert.ok(selected.at(-1) > 950, 'budget spreads across the visible graph');
  assert.deepEqual(pulsesFor(large, view), selected, 'stable camera preserves selected edges');
  assert.deepEqual(pulsesFor(large, view, 0), []);
  assert.deepEqual(pulsesFor(large, offscreen, 3), [0, 346, 692]);
  assert.equal(decorationInterval, 1000 / 30);
});

test('nearby lookup covers influence across cell boundaries and does not visit remote graph nodes', () => {
  const nodes = [];
  for (let x = -40; x <= 40; x++) for (let y = -40; y <= 40; y++) nodes.push({ x: x * 100, y: y * 100 });
  const find = nearbyNodes(nodes);
  for (const pointer of [{ x: 0, y: 0 }, { x: -280.1, y: 279.9 }, { x: 279.9, y: -280.1 }]) {
    const candidates = new Set(find(pointer));
    assert.ok(candidates.size < 100, 'remote nodes excluded from pointer work');
    nodes.forEach((node, index) => {
      if (Math.hypot(pointer.x - node.x, pointer.y - node.y) < 280) assert.ok(candidates.has(index));
    });
  }
  assert.deepEqual(find({ x: 1e6, y: -1e6 }), []);
});

test('only executing edges consume the visible pulse budget', () => {
  const view = { left: -10, right: 10, top: -10, bottom: 10 };
  const edgeBounds = Array.from({ length: 1000 }, () => view);
  const eligible = edgeBounds.map((_, index) => index === 997 || index === 999);
  assert.deepEqual(pulsesFor(edgeBounds, view, 1, eligible), [997], 'filter execution before spreading the budget');
  assert.deepEqual(pulsesFor(edgeBounds, view, 24, eligible), [997, 999]);
  assert.deepEqual(pulsesFor(edgeBounds, view, 24, edgeBounds.map(() => false)), []);
  assert.deepEqual(pulsesFor(edgeBounds, { left: 50, right: 60, top: 50, bottom: 60 }, 24, eligible), []);
});

test('pulse lookup reads eligibility once and preserves culling and budget across camera changes', () => {
  const view = { left: -10, right: 10, top: -10, bottom: 10 };
  const bounds = Array.from({ length: 10000 }, (_, i) => i % 3 ? view : { left: 50, right: 60, top: 50, bottom: 60 });
  const eligible = bounds.map((_, i) => i % 29 === 0);
  let reads = 0;
  const tracked = new Proxy(eligible, { get(target, key) { if (/^\d+$/.test(String(key))) reads++; return target[key]; } });
  const find = pulseLookup(bounds, tracked);
  assert.equal(reads, bounds.length);
  for (const camera of [view, { left: 45, right: 65, top: 45, bottom: 65 }]) {
    for (const limit of [0, 1, 24, 1000]) assert.deepEqual(find(camera, limit), pulsesFor(bounds, camera, limit, eligible));
  }
  for (let i = 0; i < 150; i++) find(view);
  assert.equal(reads, bounds.length, 'camera frames never rescan eligibility');
  assert.deepEqual(pulseLookup(bounds, bounds.map(() => false))(view), []);
});

test('magnetic offsets keep modest motion, settle exactly, and reset outside influence/reduced motion', () => {
  const node = { x: 0, y: 0 };
  const offset = offsetFor(node, { x: 100, y: -50 });
  assert.ok(offset.x > 0 && offset.x <= 3 && offset.y < 0 && offset.y >= -3);
  assert.deepEqual(offsetFor(node, { x: 100.000001, y: -50.000001 }), offset);
  assert.deepEqual(offsetFor(node, { x: 100, y: -50 }, false), { x: 0, y: 0 });
  assert.deepEqual(offsetFor(node, { x: 280, y: 0 }), { x: 0, y: 0 });
  assert.deepEqual(offsetFor(node, { x: 0, y: 0 }), { x: 0, y: 0 });
  assert.deepEqual(offsetFor(node, { x: -.00001, y: .00001 }), { x: 0, y: 0 });
});

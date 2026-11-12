const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { buildSync } = require('esbuild');
const output = buildSync({
  entryPoints: [path.join(__dirname, '../src/webview/workbench/mindmapFollowGesture.ts')],
  bundle: true, platform: 'node', format: 'cjs', write: false
}).outputFiles[0].text;
const compiled = { exports: {} };
new Function('module', 'exports', output)(compiled, compiled.exports);
const { mindmapFollowPan, mindmapFollowZoom, mindmapFollowWheel, mindmapFollowTrackpad, mindmapFollowWheelResponse, mindmapWheelDelta,
  MINDMAP_FOLLOW_WHEEL_THRESHOLD, MINDMAP_FOLLOW_WHEEL_IDLE, MINDMAP_FOLLOW_ZOOM_THRESHOLD } = compiled.exports;

test('wheel intent uses net normalized displacement within one burst, including long-lived viewers', () => {
  for (const start of [0, 2e6, 1e10]) {
    let state;
    for (let index = 0; index < 12; index++) {
      state = mindmapFollowWheel(state, 100, 0, start + index * 30);
      assert.equal(mindmapFollowWheelResponse(state).released, false);
    }
    state = mindmapFollowWheel(state, 1, 0, start + 360);
    assert.equal(mindmapFollowWheelResponse(state).released, true);
    assert.ok(mindmapFollowWheelResponse(state).x > 150, 'a long stroke visibly bends before release');
    state = mindmapFollowWheel(state, -1201, 0, start + 370);
    assert.ok(Math.abs(state.x) < 1e-8, 'reversals cancel intent rather than adding travel distance');
    assert.equal(mindmapFollowWheelResponse(state).released, false);
    assert.equal(state.time, start + 370);
    state = mindmapFollowWheel(state, 20, 0, start + 370 + MINDMAP_FOLLOW_WHEEL_IDLE);
    assert.equal(state.x, 20);
    for (let index = 1; index < 40; index++) {
      state = mindmapFollowWheel(state, 20, 0, start + 370 + MINDMAP_FOLLOW_WHEEL_IDLE * (index + 1));
      assert.equal(state.x, 20, 'tiny separated gestures cannot disable follow later');
    }
  }
  assert.deepEqual(mindmapWheelDelta(2, 3, 1, 600), { x: 36, y: 54 });
  assert.deepEqual(mindmapWheelDelta(0, .5, 2, 600, true), { x: 300, y: 0 });
  assert.deepEqual(mindmapWheelDelta(2, 3, 0, 600, true), { x: 2, y: 3 });
});

test('trackpad bends over a long progressively resistant stroke with distance-based release', () => {
  const response = distance => mindmapFollowWheelResponse(mindmapFollowWheel(undefined, distance, 0, 0));
  assert.ok(response(70).x > 8 && response(70).x < 20, 'small input feels soft and visibly follows');
  assert.ok(response(1100).x > response(600).x, 'the long stroke keeps moving');
  assert.ok(response(1100).x - response(1000).x < response(100).x, 'resistance increases as it bends');
  const held = response(MINDMAP_FOLLOW_WHEEL_THRESHOLD), released = response(MINDMAP_FOLLOW_WHEEL_THRESHOLD + .001);
  assert.equal(held.released, false); assert.equal(released.released, true);
  assert.ok(Math.abs(released.x - held.x) < .001, 'release has no positional jump or hold-time gate');
  const pinched = mindmapFollowWheelResponse(mindmapFollowWheel(undefined, 0, 70, 0), true);
  assert.equal(pinched.released, true);
  assert.ok(pinched.factor > 1.2 && pinched.factor < 1.5, 'pinch visibly bends before release');
});

test('zoom intent is symmetric, resistant and continuous across release and reversals', () => {
  for (const direction of [-1, 1]) {
    const held = mindmapFollowZoom(direction * MINDMAP_FOLLOW_ZOOM_THRESHOLD);
    const released = mindmapFollowZoom(direction * (MINDMAP_FOLLOW_ZOOM_THRESHOLD + 1e-6));
    assert.equal(held.released, false); assert.equal(released.released, true);
    assert.ok(Math.abs(held.factor - released.factor) < 2e-6);
    assert.ok(Math.abs(held.factor - 1) > .1 && Math.abs(held.factor - 1) < .25, 'pinch is soft but still resists near release');
  }
  let log = Math.log(1.1) + Math.log(1.1) + Math.log(1 / 1.1);
  assert.equal(mindmapFollowZoom(log).released, false);
  log += Math.log(1.6);
  assert.equal(mindmapFollowZoom(log).released, true);
  assert.deepEqual(mindmapFollowZoom(0), { factor: 1, released: false });
});

test('zero and malformed deltas never release follow or poison the camera', () => {
  assert.deepEqual(mindmapFollowPan(0, 0), { x: 0, y: 0, released: false });
  assert.deepEqual(mindmapFollowPan(NaN, Infinity), { x: 0, y: 0, released: false });
  assert.deepEqual(mindmapFollowZoom(NaN), { factor: 1, released: false });
  for (const value of [Number.MAX_VALUE, -Number.MAX_VALUE, Infinity, NaN]) {
    const delta = mindmapWheelDelta(value, value, 2, Number.MAX_VALUE);
    const state = mindmapFollowWheel(undefined, delta.x, delta.y, 1e10);
    const pan = mindmapFollowPan(state.x, state.y);
    assert.ok(Number.isFinite(pan.x) && Number.isFinite(pan.y));
    assert.ok(Number.isFinite(mindmapFollowZoom(value).factor));
  }
});

test('trackpad acceleration is compressed radially and consistently across event cadences', () => {
  const spike = mindmapFollowTrackpad(undefined, 700, 0, 0, false);
  assert.ok(spike.x > 40 && spike.x < 51, 'one accelerated packet cannot become a long gesture');
  assert.equal(mindmapFollowWheelResponse(spike).released, false);
  const diagonal = mindmapFollowTrackpad(undefined, 300, -400, 0, false);
  assert.ok(Math.abs(diagonal.x / diagonal.y + .75) < 1e-9, 'both axes share a gain');
  const travels = [8, 16, 32].map(interval => {
    let state;
    for (let time = 0; time < 960; time += interval) state = mindmapFollowTrackpad(state, interval, 0, time, false);
    return state.x;
  });
  assert.ok(Math.max(...travels)-Math.min(...travels) < 4, JSON.stringify(travels));
  let state;
  for (let i = 0; i < 40; i++) state = mindmapFollowTrackpad(state, 100, 0, 1e10+i*16, false);
  assert.equal(mindmapFollowWheelResponse(state).released, true, 'a continuous deliberate long stroke still releases');
  const reset = mindmapFollowTrackpad(state, 10, 0, state.time+MINDMAP_FOLLOW_WHEEL_IDLE, false);
  assert.ok(reset.x > 9 && reset.x < 10, 'separate gestures start fresh');
});

test('native momentum freezes intent, while unsupported browsers detect sustained deceleration', () => {
  for (const native of [true, false]) {
    let state, time = 0;
    const direct = native ? false : undefined;
    for (const delta of [12, 40, 100, 200, 260, 180]) {
      state = mindmapFollowTrackpad(state, delta, 0, time, direct); time += 16;
      assert.equal(state.pan.momentum, false);
    }
    let frozen;
    for (const delta of [140, 110, 80, 55, 34, 21, 13, 8, 5, 3, 2, 1, .5, .25]) {
      state = mindmapFollowTrackpad(state, delta, 0, time, native ? true : undefined); time += 16;
      if (frozen !== undefined) assert.equal(state.x, frozen, 'tail never adds release intent');
      if (state.pan.momentum) frozen = state.x;
      assert.equal(mindmapFollowWheelResponse(state).released, false);
    }
    assert.ok(frozen !== undefined, 'tail detected');
    const continued = mindmapFollowTrackpad(state, -120, 0, time, direct);
    assert.equal(continued.pan.momentum, false);
    assert.ok(continued.x < -40 && continued.x > -51, 'new stroke resets old intent for a visible-position rebase');
    const faster = mindmapFollowTrackpad(state, 120, 0, time, direct);
    assert.equal(faster.pan.momentum, false, 'same-direction renewed input also resumes');
  }
});

test('steady long input never becomes momentum and explicit platform phases override heuristics', () => {
  const tail = mindmapFollowTrackpad(mindmapFollowTrackpad(undefined, 200, 0, 0), 100, 0, 16, true);
  const turn = mindmapFollowTrackpad(tail, 0, 4, 32);
  assert.equal(turn.pan.momentum, false, 'perpendicular renewed input resumes even below the previous tail speed');
  assert.equal(turn.x, 0); assert.ok(turn.y > 3.9 && turn.y < 4);
  let state;
  for (let i = 0; i < 150; i++) {
    state = mindmapFollowTrackpad(state, 6, 8, i*16);
    assert.equal(state.pan.momentum, false, 'holding a steady long gesture never starts a replay');
  }
  let slowing = mindmapFollowTrackpad(undefined, 200, 0, 0, false);
  for (let i = 1; i <= 12; i++) {
    slowing = mindmapFollowTrackpad(slowing, 200*.6**i, 0, i*16, false);
    assert.equal(slowing.pan.momentum, false, 'explicit direct contact takes priority over fallback');
  }
  for (const value of [NaN, Infinity, -Number.MAX_VALUE]) {
    const invalid = mindmapFollowTrackpad(undefined, value, value, value);
    assert.ok(Number.isFinite(invalid.x) && Number.isFinite(invalid.y) && Number.isFinite(invalid.time));
  }
});

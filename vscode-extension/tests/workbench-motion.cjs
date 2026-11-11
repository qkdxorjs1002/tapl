const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { buildSync } = require('esbuild');
const output = buildSync({ entryPoints: [path.join(__dirname, '../src/webview/workbench/workbenchMotion.ts')], bundle: true, platform: 'node', format: 'cjs', write: false }).outputFiles[0].text;
const compiled = { exports: {} };
new Function('module', 'exports', output)(compiled, compiled.exports);
const { animateWorkbench, workbenchMotionIdentity: identity, pageMotionReady } = compiled.exports;

function surface(reduced = false) {
  const media = new EventTarget(); media.matches = reduced;
  const previous = global.matchMedia;
  global.matchMedia = () => media;
  const animations = [];
  const element = { animate(frames, options) {
    const animation = new EventTarget(); animation.cancelled = 0;
    animation.cancel = () => { animation.cancelled++; };
    animations.push({ animation, frames, options });
    return animation;
  } };
  return { media, element, animations, restore() { global.matchMedia = previous; } };
}
test('navigation identities retain RUN/source/detail changes but ignore result data, search input and pagination', () => {
  const route = { runKey: '["source-a","RUN-1"]', page: 'records', view: { type: 'records', query: '', offset: 0, results: [] } };
  assert.equal(identity(route), identity({ ...route, view: { ...route.view, query: 'typing', offset: 50, results: [{ id: 2 }] } }));
  assert.notEqual(identity(route), identity({ ...route, runKey: '["source-b","RUN-1"]' }));
  assert.notEqual(identity(route), identity({ ...route, page: 'settings', view: undefined }));
  const detail = { ...route, page: 'legacy', view: { type: 'searchItem', result: { source_db: 'source-a', id: 7 } } };
  assert.notEqual(identity(detail), identity({ ...detail, view: { ...detail.view, result: { source_db: 'source-a', id: 8 } } }));
  assert.notEqual(identity(detail), identity({ ...detail, view: { ...detail.view, result: { source_db: 'source-b', id: 7 } } }));
  assert.equal(identity(detail), identity({ ...detail, view: { ...detail.view, result: { ...detail.view.result, title: 'polled title' } } }));
});
test('pending destinations wait for content, and a completed identity never replays on polling', () => {
  let previous = 'current';
  assert.equal(pageMotionReady(previous, 'detail', false), false);
  assert.equal(pageMotionReady(previous, 'detail', true), true);
  previous = 'detail';
  assert.equal(pageMotionReady(previous, 'detail', true), false);
  assert.equal(pageMotionReady(previous, 'detail', false), false);
  assert.equal(pageMotionReady(previous, 'other-detail', true), true);
});
test('finishing releases fill styles and listeners exactly once; cancellation cannot remove a reopened surface', () => {
  const fixture = surface();
  try {
    let removed = 0;
    const cancel = animateWorkbench(fixture.element, 'panel', false, () => removed++);
    const first = fixture.animations[0].animation;
    cancel(); // reopen cancels the stale exit
    first.dispatchEvent(new Event('finish'));
    fixture.media.matches = true; fixture.media.dispatchEvent(new Event('change'));
    assert.equal(removed, 0);
    fixture.media.matches = false;
    animateWorkbench(fixture.element, 'dialog', false, () => removed++);
    const second = fixture.animations[1].animation;
    second.dispatchEvent(new Event('finish')); second.dispatchEvent(new Event('finish'));
    assert.equal(removed, 1); assert.equal(second.cancelled, 1);
  } finally { fixture.restore(); }
});
test('reduced motion completes exits synchronously and changing preference finishes active motion without a timer', () => {
  const fixture = surface(true);
  try {
    let completed = 0;
    animateWorkbench(fixture.element, 'scrim', false, () => completed++);
    assert.equal(completed, 1); assert.equal(fixture.animations.length, 0);
    fixture.media.matches = false;
    animateWorkbench(fixture.element, 'dialog', false, () => completed++);
    fixture.media.matches = true; fixture.media.dispatchEvent(new Event('change'));
    assert.equal(completed, 2); assert.equal(fixture.animations[0].animation.cancelled, 1);
    fixture.animations[0].animation.dispatchEvent(new Event('finish'));
    assert.equal(completed, 2);
  } finally { fixture.restore(); }
});
test('page and scrim motion never transform camera coordinates, while panels use a short bounded displacement', () => {
  const fixture = surface();
  try {
    for (const kind of ['page', 'scrim', 'panel']) {
      const cancel = animateWorkbench(fixture.element, kind, true);
      const { frames, options } = fixture.animations.at(-1);
      assert.ok(options.duration <= 180);
      if (kind !== 'panel') assert.ok(frames.every(frame => !('transform' in frame)));
      else assert.equal(frames[0].transform, 'translateY(5px)');
      cancel();
    }
  } finally { fixture.restore(); }
});

const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { buildSync } = require('esbuild');
const output = buildSync({ entryPoints: [path.join(__dirname, '../src/webview/workbench/mindmapCache.ts')], bundle: true, platform: 'node', format: 'cjs', write: false }).outputFiles[0].text;
const compiled = { exports: {} };
new Function('module', 'exports', output)(compiled, compiled.exports);
const equal = compiled.exports.sameMindmapValue;
const { runMindmapProjection, memoryMindmapProjection, latestMindmapItem } = compiled.exports;

test('snapshot equality includes record content, provenance, execution, ordering and optional fields', () => {
  const snapshot = { run: { id: 'same', source_db: 'a', status: 'active' }, tasks: [
    { id: 1, status: 'Pending', body: 'original', custom_fields: { nested: [1, null, { value: true }] } },
    { id: 2, status: 'Pending' }
  ] };
  assert.ok(equal(snapshot, structuredClone(snapshot)));
  assert.ok(equal({ a: 1, b: 2 }, { b: 2, a: 1 }), 'object key order is immaterial');
  for (const change of [
    value => { value.run.source_db = 'b'; },
    value => { value.run.status = 'completed'; },
    value => { value.tasks[0].body = 'new'; },
    value => { value.tasks[0].status = 'In Progress'; },
    value => { value.tasks[0].custom_fields.nested[2].value = false; },
    value => { value.tasks.reverse(); },
    value => { value.tasks.pop(); }
  ]) {
    const next = structuredClone(snapshot); change(next); assert.equal(equal(snapshot, next), false);
  }
  assert.equal(equal({ a: undefined }, {}), false);
  assert.equal(equal([1], { 0: 1 }), false);
  assert.equal(equal(null, {}), false);
});

test('RUN projection ignores timing and bodies while latest navigation preserves current details', () => {
  const snapshot = { run: { id: 'run', source_db: 'local', status: 'active' }, plans: [], tasks: [
    { id: 1, stable_id: 'TASK-001', kind: 'task', title: 'Task', status: 'Completed', body: 'old', execution_timing: { elapsed_seconds: 10, as_of: 'first' } }
  ] };
  const next = structuredClone(snapshot);
  next.tasks[0].execution_timing.as_of = 'second';
  next.tasks[0].body = 'latest';
  next.tasks[0].custom_fields = { large: 'detail only' };
  next.findings = [{ body: 'new finding' }];
  assert.equal(equal(snapshot, next), false, 'global JSON equality still detects detail changes');
  assert.ok(equal(runMindmapProjection(snapshot), runMindmapProjection(next)));
  assert.equal(latestMindmapItem(next, snapshot.tasks[0]), next.tasks[0]);
  assert.equal(latestMindmapItem(next, snapshot.tasks[0]).body, 'latest');
  const peer = { ...next.tasks[0], source_db: 'peer', body: 'foreign' };
  next.tasks.unshift(peer);
  assert.equal(latestMindmapItem(next, snapshot.tasks[0]).body, 'latest', 'equal numeric IDs stay source safe');
});

test('RUN projection includes every visible identity, status, parent, ordering and title input', () => {
  const snapshot = { run: { id: 'r', source_db: 'a', status: 'active', request_summary: 'Request', slug: 'fallback' },
    plans: [{ id: 3, stable_id: 'PLAN-1', kind: 'plan', title: 'Plan' }],
    tasks: [{ id: 1, stable_id: 'TASK-1', kind: 'task', title: 'Task', status: 'Pending', spec_id: 'PLAN-1' }, { id: 2, stable_id: 'TASK-2', kind: 'task', title: 'Other' }] };
  for (const change of [
    value => { value.run.status = 'completed'; }, value => { value.run.source_db = 'b'; },
    value => { value.run.id = 'other'; }, value => { value.run.request_summary = 'New'; }, value => { value.run.slug = 'new'; },
    ...['id', 'stable_id', 'kind', 'title', 'status', 'source_db', 'run_id', 'spec_id'].map(field => value => { value.tasks[0][field] = 'changed'; }),
    value => { value.tasks.reverse(); }, value => { value.plans[0].title = 'New plan'; }, value => { value.tasks.pop(); }
  ]) {
    const next = structuredClone(snapshot); change(next);
    assert.equal(equal(runMindmapProjection(snapshot), runMindmapProjection(next)), false);
  }
});

test('memory projection excludes decay and source detail bodies, retaining displayed fields and relations', () => {
  const memories = [{ id: 'm', source_db: 'a', note: 'Note', cue: ['cue'], state: 'active', revision: 1,
    source: { kind: 'item', run_id: 'r', item_id: 1, title: 'Source' }, matched_cues: ['cue'], source_available: true, strength: 1 }];
  const next = structuredClone(memories); next[0].strength = .9; next[0].source_record = { item: { body: 'new body' } };
  assert.ok(equal(memoryMindmapProjection(memories), memoryMindmapProjection(next)));
  for (const change of [
    value => { value[0].note = 'New'; }, value => { value[0].cue = ['other']; }, value => { value[0].matched_cues = []; },
    value => { value[0].state = 'superseded'; }, value => { value[0].revision++; }, value => { value[0].source_available = false; },
    ...['id', 'source_db'].map(field => value => { value[0][field] = 'other'; }),
    ...['kind', 'run_id', 'item_id', 'title'].map(field => value => { value[0].source[field] = 'other'; })
  ]) {
    const changed = structuredClone(memories); change(changed);
    assert.equal(equal(memoryMindmapProjection(memories), memoryMindmapProjection(changed)), false);
  }
});

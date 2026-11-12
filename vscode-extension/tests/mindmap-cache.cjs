const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { buildSync } = require('esbuild');
const output = buildSync({ entryPoints: [path.join(__dirname, '../src/webview/workbench/mindmapCache.ts')], bundle: true, platform: 'node', format: 'cjs', write: false }).outputFiles[0].text;
const compiled = { exports: {} };
new Function('module', 'exports', output)(compiled, compiled.exports);
const equal = compiled.exports.sameMindmapValue;

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

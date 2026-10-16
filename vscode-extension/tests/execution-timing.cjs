const { test } = require('node:test');
const assert = require('node:assert/strict');
const esbuild = require('esbuild');
const path = require('node:path');

const { outputFiles } = esbuild.buildSync({
  entryPoints: [path.join(__dirname, '../src/webview/executionTiming.ts')],
  bundle: true,
  platform: 'node',
  format: 'cjs',
  write: false
});
const compiled = { exports: {} };
new Function('module', 'exports', outputFiles[0].text)(compiled, compiled.exports);
const { formatExecutionTiming } = compiled.exports;

const snapshot = {
  started_at: '2026-10-16T00:00:00Z',
  finished_at: null,
  elapsed_seconds: 83,
  running_since: '2026-10-16T00:01:00Z',
  as_of: '2026-10-16T00:01:30Z'
};
const asOf = Date.parse(snapshot.as_of);

test('missing timing is unmeasured and zero is a measured duration', () => {
  assert.equal(formatExecutionTiming(null, 'Pending', 'ko', asOf), null);
  assert.deepEqual(formatExecutionTiming({ ...snapshot, elapsed_seconds: 0, running_since: null }, 'Pending', 'ko', asOf), {
    running: false, duration: '0초'
  });
});

test('running duration adds time after the snapshot and is localized', () => {
  assert.deepEqual(formatExecutionTiming(snapshot, 'In Progress', 'ko', asOf), {
    running: true, duration: '1분 23초'
  });
  assert.deepEqual(formatExecutionTiming(snapshot, 'In Progress', 'en', asOf + 2000), {
    running: true, duration: '1m 25s'
  });
  assert.equal(formatExecutionTiming(snapshot, 'In Progress', 'en', asOf - 1000)?.duration, '1m 23s');
});

test('completed and blocked tasks hold the accumulated value', () => {
  for (const status of ['Completed', 'Blocked']) {
    assert.deepEqual(formatExecutionTiming(snapshot, status, 'ko', asOf + 60000), {
      running: false, duration: '1분 23초'
    });
  }
  assert.equal(formatExecutionTiming({ ...snapshot, running_since: null, elapsed_seconds: 3601 }, 'Completed', 'en', asOf + 60000)?.duration, '1h 1s');
});

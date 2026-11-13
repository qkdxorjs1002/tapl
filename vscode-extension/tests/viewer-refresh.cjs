const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');
const compiled = buildSync({ entryPoints: [path.join(__dirname, '../src/viewerRefresh.ts')],
  bundle: true, platform: 'node', format: 'cjs', write: false }).outputFiles[0].text;
const mod = new Module(__filename, module); mod.filename = __filename; mod.paths = module.paths; mod._compile(compiled, __filename);
const { databaseRevision, DatabaseRevisions, ViewerRefreshQueue } = mod.exports;
const tick = () => new Promise(resolve => setImmediate(resolve));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

function workspace(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'tapl-revision-'));
  const directory = path.join(root, '.tapl'); fs.mkdirSync(directory);
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { root, directory, write(name, size = 64) { fs.writeFileSync(path.join(directory, name), Buffer.alloc(size)); } };
}

test('revision ignores read sidecars and catches WAL reuse, checkpoint, replacements and sources', async t => {
  const { root, directory, write } = workspace(t);
  write('tapl.db', 4096);
  const before = (await databaseRevision(root));
  write('tapl.db-shm', 32768); write('tapl.db-wal', 0);
  assert.equal((await databaseRevision(root)), before);
  write('tapl.db-wal', 32);
  assert.equal((await databaseRevision(root)), before, 'a WAL header contains no frames');
  fs.unlinkSync(path.join(directory, 'tapl.db-wal'));
  assert.equal((await databaseRevision(root)), before);
  write('tapl.db-wal', 128);
  const frames = (await databaseRevision(root)); assert.notEqual(frames, before);
  await pause(2); write('tapl.db-wal', 128);
  const reused = (await databaseRevision(root)); assert.notEqual(reused, frames, 'same-size WAL writes retain high resolution metadata');
  fs.unlinkSync(path.join(directory, 'tapl.db-wal')); write('tapl.db', 8192);
  const checkpoint = (await databaseRevision(root)); assert.notEqual(checkpoint, reused);
  write('replacement', 8192); fs.renameSync(path.join(directory, 'replacement'), path.join(directory, 'tapl.db'));
  const replaced = (await databaseRevision(root)); assert.notEqual(replaced, checkpoint, 'replacement inode is included');
  write('tapl-peer.db'); const peer = (await databaseRevision(root)); assert.notEqual(peer, replaced);
  fs.unlinkSync(path.join(directory, 'tapl-peer.db')); assert.equal((await databaseRevision(root)), replaced);
  write('unrelated.db'); write('config.toml'); assert.equal((await databaseRevision(root)), replaced);
});

test('snapshot reads detect commits without consuming the shared refresh revision', async () => {
  let revision = 'a'; const revisions = new DatabaseRevisions(() => revision);
  assert.equal(revisions.changed('first', 'a'), true);
  assert.equal(await revisions.observe('first', 'a', false), true);
  assert.equal(revisions.changed('first', 'a'), true, 'failed or stale result cannot establish a baseline');
  revision = 'b'; assert.equal(await revisions.observe('first', 'a', true), false);
  assert.equal(revisions.changed('first', 'b'), true, 'a commit during read is not silently approved');
  assert.equal(await revisions.observe('first', 'b', true), true);
  assert.equal(revisions.changed('first', 'b'), true, 'one consumer cannot hide changes from other views');
  revisions.accept('first', 'b');
  assert.equal(revisions.changed('first', 'b'), false);
  assert.equal(revisions.changed('second', 'b'), true, 'workspace baselines remain separate');
  revision = undefined; assert.equal(revisions.changed('first', revision), true);
  assert.equal(await revisions.observe('first', undefined, true), true, 'stat failures permit refresh without an endless forced loop');
});

test('queue coalesces bursts, serializes refreshes and retains one forced in-flight pass', async t => {
  let revision = 'a', calls = 0, active = 0, maximum = 0, release;
  const revisions = new DatabaseRevisions(() => revision);
  const queue = new ViewerRefreshQueue(() => 'first', revisions, async () => {
    calls++; active++; maximum = Math.max(maximum, active);
    const before = revision;
    if (calls === 1) await new Promise(resolve => { release = resolve; });
    await revisions.observe('first', before, true); active--;
  }, 5); t.after(() => queue.dispose());
  const first = queue.request(true);
  queue.request(true); queue.request(true);
  while (!release) await tick();
  queue.schedule('first'); queue.request(true); queue.request(true);
  release(); await first;
  assert.equal(calls, 2); assert.equal(maximum, 1);
  queue.schedule('first'); queue.schedule('first'); await pause(15);
  assert.equal(calls, 2, 'unchanged read-sidecar burst is a metadata check only');
  revision = 'b'; queue.schedule('other'); await pause(15); assert.equal(calls, 2);
  queue.schedule('first'); queue.schedule('first'); await pause(15); assert.equal(calls, 3);
  await queue.request(true); assert.equal(calls, 4, 'explicit refresh bypasses the revision gate');
});

test('a commit during an in-flight snapshot queues one read of the unapproved revision', async t => {
  let revision = 'a', calls = 0, release;
  const revisions = new DatabaseRevisions(() => revision);
  const queue = new ViewerRefreshQueue(() => 'first', revisions, async () => {
    calls++; const before = revision;
    if (calls === 1) await new Promise(resolve => { release = resolve; });
    if (!await revisions.observe('first', before, true)) queue.schedule('first');
  }, 5); t.after(() => queue.dispose());
  const pending = queue.request(true); while (!release) await tick();
  revision = 'b'; queue.schedule('first'); release(); await pending;
  assert.equal(calls, 1, 'automatic trailing reads retain the debounce');
  await pause(15);
  assert.equal(calls, 2); assert.equal(revisions.changed('first', 'b'), false);
});

test('unavailable metadata falls back to refresh and never suppresses later data', async t => {
  let revision, calls = 0;
  const revisions = new DatabaseRevisions(() => revision);
  const queue = new ViewerRefreshQueue(() => 'first', revisions, async () => {
    calls++; await revisions.observe('first', revision, true);
  }, 5); t.after(() => queue.dispose());
  await queue.request(); await queue.request(); assert.equal(calls, 2);
  revision = 'known'; await queue.request(); assert.equal(calls, 3);
  await queue.request(); assert.equal(calls, 3);
});


test('continuous commits yield to the debounce instead of draining a hot loop', { timeout: 2000 }, async t => {
  let revision = 'initial', calls = 0, done;
  const times = [], finished = new Promise(resolve => { done = resolve; });
  const revisions = new DatabaseRevisions(() => revision);
  const queue = new ViewerRefreshQueue(() => 'first', revisions, async () => {
    calls++; times.push(performance.now());
    const before = await revisions.read('first');
    revision = `commit-${calls}`;
    if (!await revisions.observe('first', before, true)) queue.schedule('first');
    if (calls === 3) { queue.dispose(); done(); }
  }, 25); t.after(() => queue.dispose());
  await queue.request(true); assert.equal(calls, 1);
  await finished;
  assert.ok(times[1] - times[0] >= 20);
  assert.ok(times[2] - times[1] >= 20);
});

test('async metadata never approves a snapshot invalidated during capture', async () => {
  let valid = true, release;
  const revisions = new DatabaseRevisions(() => new Promise(resolve => { release = resolve; }));
  const pending = revisions.observe('first', 'a', () => valid);
  valid = false; release('a');
  assert.equal(await pending, true);
  assert.equal(revisions.changed('first', 'a'), true);
});

test('workspace changes during async metadata capture read only the current workspace', async t => {
  let workspace = 'first', release;
  const calls = [];
  const revisions = new DatabaseRevisions(root => root === 'first' ? new Promise(resolve => { release = resolve; }) : 'b');
  const queue = new ViewerRefreshQueue(() => workspace, revisions, async () => { calls.push(workspace); }, 5);
  t.after(() => queue.dispose());
  const pending = queue.request(true);
  while (!release) await tick();
  workspace = 'second'; release('a');
  await pending; assert.deepEqual(calls, ['second']);
});

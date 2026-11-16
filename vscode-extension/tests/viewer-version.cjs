const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const path = require('node:path');
const { buildSync } = require('esbuild');
const output = buildSync({ entryPoints: [path.resolve(__dirname, '../src/webview/viewerRelease.ts')],
  bundle: true, platform: 'node', format: 'cjs', write: false }).outputFiles[0].text;
const compiled = new Module(__filename, module); compiled.filename = __filename; compiled.paths = module.paths;
compiled._compile(output, __filename);
const { createReleaseChecker, isNewerRelease, stableRelease, releaseUrl, RELEASE_API,
  RELEASE_CACHE_KEY, RELEASE_CACHE_MS, RELEASE_RETRY_MS } = compiled.exports;
const response = (tag, extra = {}) => ({ ok: true, json: async () => ({ tag_name: tag, draft: false, prerelease: false, ...extra }) });
const storage = () => { const values = new Map(); return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }; };

test('stable update comparison respects numeric versions, prereleases and build metadata', () => {
  for (const [latest, current, expected] of [
    ['2.22.0', '2.21.4', true], ['2.10.0', '2.9.9', true], ['2.21.4', '2.21.4', false],
    ['v2.21.4', '2.21.4-beta.1', true], ['2.21.3', '2.21.4-beta.1', false],
    ['2.21.4+build.2', '2.21.4+build.1', false], ['2.22.0-beta.1', '2.21.4', false],
    ['2.21.4', '2.21.4-01', false], ['9007199254740993.0.0', '9007199254740992.0.0', true],
    ['https://evil.example', '2.1.0', false], ['02.2.0', '2.1.0', false], ['2.2.0', 'broken', false]
  ]) assert.equal(isNewerRelease(latest, current), expected, `${latest} > ${current}`);
});

test('release parsing rejects drafts, prereleases and unsafe tags, and builds only fixed repository links', () => {
  const release = { tag_name: 'v2.22.0', draft: false, prerelease: false, html_url: 'https://evil.example' };
  assert.deepEqual(stableRelease(release), { tag: 'v2.22.0', version: '2.22.0' });
  assert.equal(releaseUrl(release.tag_name), 'https://github.com/qkdxorjs1002/tapl/releases/tag/v2.22.0');
  assert.equal(releaseUrl('2.22.0-beta.1'), 'https://github.com/qkdxorjs1002/tapl/releases/tag/2.22.0-beta.1');
  for (const patch of [{draft: true}, {prerelease: true}, {tag_name: '2.22.0-beta.1'}, {tag_name: '../other'},
    {tag_name: 'javascript:alert(1)'}, {tag_name: '<script>'}, {tag_name: '2.22.0\n'}, {tag_name: '1'.repeat(200)}, {tag_name: null}]) {
    assert.equal(stableRelease({...release, ...patch}), undefined);
  }
  assert.equal(stableRelease({ tag_name: '2.22.0' }), undefined);
  assert.equal(releaseUrl('../other'), 'https://github.com/qkdxorjs1002/tapl/releases');
});

test('requests are coalesced, unauthenticated and cached across reloads until the one-hour expiry', async () => {
  const disk = storage(); let time = 1000000, calls = 0, finish;
  const fetch = async (url, options) => {
    calls++; assert.equal(url, RELEASE_API); assert.equal(options.credentials, 'omit');
    assert.equal(options.referrerPolicy, 'no-referrer'); assert.equal(options.headers.Authorization, undefined);
    await new Promise(resolve => { finish = resolve; }); return response('2.22.0');
  };
  const checker = createReleaseChecker({ fetch, storage: disk, now: () => time });
  const first = checker.check(), second = checker.check(); assert.equal(first, second); assert.equal(calls, 1);
  finish(); await first; await checker.check(); assert.equal(calls, 1);
  const restored = createReleaseChecker({ fetch: async () => { calls++; return response('2.23.0'); }, storage: disk, now: () => time });
  assert.equal(restored.cached().version, '2.22.0'); await restored.check(); assert.equal(calls, 1);
  time += RELEASE_CACHE_MS; assert.equal((await restored.check()).version, '2.23.0'); assert.equal(calls, 2);
});

test('HTTP/JSON failures retain the last valid release and back off for five minutes', async () => {
  let time = 1000000, calls = 0;
  const checker = createReleaseChecker({ now: () => time, fetch: async () => {
    calls++; if (calls === 1) return response('2.22.0'); if (calls === 2) return {ok: false};
    if (calls === 3) return response('malformed'); return response('2.23.0');
  }});
  await checker.check(); time += RELEASE_CACHE_MS;
  assert.equal((await checker.check()).version, '2.22.0'); await checker.check(); assert.equal(calls, 2);
  time += RELEASE_RETRY_MS; assert.equal((await checker.check()).version, '2.22.0');
  time += RELEASE_RETRY_MS; assert.equal((await checker.check()).version, '2.23.0');
});

test('stalled fetch and response body time out, release in-flight state and permit a later retry', async () => {
  for (const stallBody of [false, true]) {
    let time = 1000000, calls = 0, signal;
    const checker = createReleaseChecker({ now: () => time, timeoutMs: 10, fetch: async (_url, options) => {
      calls++; signal = options.signal;
      if (calls > 1) return response('2.22.0');
      return stallBody ? {ok: true, json: () => new Promise(() => {})} : new Promise(() => {});
    }});
    assert.equal(await checker.check(), undefined); assert.equal(signal.aborted, true);
    await checker.check(); assert.equal(calls, 1);
    time += RELEASE_RETRY_MS; assert.equal((await checker.check()).version, '2.22.0');
  }
});

test('unavailable, malformed and future-dated storage do not break release checking', async () => {
  for (const disk of [
    {getItem() {throw new Error('Denied');}, setItem() {throw new Error('Denied');}},
    {getItem: () => '{', setItem() {}},
    {getItem: () => JSON.stringify({checkedAt: 100000000, retryAt: 100000001, release: {tag: '2.23.0'}}), setItem() {}}
  ]) {
    let calls = 0;
    const checker = createReleaseChecker({storage: disk, now: () => 1000000, fetch: async () => {calls++; return response('2.22.0');}});
    assert.equal((await checker.check()).version, '2.22.0'); assert.equal(calls, 1);
  }
  const disk = storage(); let time = 1000000, calls = 0;
  const options = {storage: disk, now: () => time, fetch: () => {calls++; throw new Error('Offline');}};
  await createReleaseChecker(options).check(); await createReleaseChecker(options).check(); assert.equal(calls, 1);
  time += RELEASE_RETRY_MS; await createReleaseChecker(options).check(); assert.equal(calls, 2);
  assert.ok(JSON.parse(disk.getItem(RELEASE_CACHE_KEY)).retryAt > time);
});

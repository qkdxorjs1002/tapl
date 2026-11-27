const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const path = require('node:path');
const { buildSync } = require('esbuild');
const { version: extensionVersion } = require('../package.json');

function loadRelease(ctlTag = '') {
  const { outputFiles } = buildSync({
    entryPoints: [path.resolve(__dirname, '../src/webview/viewerRelease.ts')],
    bundle: true, platform: 'node', format: 'cjs', write: false,
    define: { __TAPL_CTL_RELEASE_TAG__: JSON.stringify(ctlTag) }
  });
  const compiled = new Module(__filename, module);
  compiled.filename = __filename;
  compiled.paths = module.paths;
  compiled._compile(outputFiles[0].text, __filename);
  return compiled.exports;
}

function release(tag, overrides = {}) {
  return { tag_name: tag, draft: false, prerelease: false, ...overrides };
}

test('build identities use the unmodified ctl tag in the browser and the extension version in VS Code', () => {
  const ctlTag = 'v90.1.0-rc1';
  const { installedViewerRelease, releaseUrl } = loadRelease(ctlTag);
  assert.deepEqual(installedViewerRelease(true), { tag: ctlTag, version: '90.1.0-rc1' });
  assert.deepEqual(installedViewerRelease(false), { tag: `viewer-${extensionVersion}`, version: extensionVersion });
  assert.equal(releaseUrl(installedViewerRelease(true).tag), `https://github.com/qkdxorjs1002/tapl/releases/tag/${ctlTag}`);
  assert.equal(releaseUrl(installedViewerRelease(false).tag), `https://github.com/qkdxorjs1002/tapl/releases/tag/viewer-${extensionVersion}`);
  for (const unstampedTag of ['', 'invalid', 'viewer-90.1.0']) {
    assert.deepEqual(loadRelease(unstampedTag).installedViewerRelease(true), { tag: extensionVersion, version: extensionVersion });
  }
});

test('Viewer discovery selects the highest stable version across pages using fixed repository URLs', async () => {
  const { createReleaseChecker, VIEWER_RELEASES_API } = loadRelease();
  const requests = [];
  const checker = createReleaseChecker({ channel: 'viewer', fetch: async (url, options) => {
    requests.push(url);
    assert.equal(options.credentials, 'omit');
    assert.equal(options.referrerPolicy, 'no-referrer');
    assert.equal(options.priority, 'low');
    if (requests.length === 1) {
      return Response.json([
        release('99.0.0'),
        release('viewer-50.0.0', { draft: true }),
        release('viewer-40.0.0', { prerelease: true }),
        release('viewer-30.0.0-beta1'),
        release('viewer-v20.0.0'),
        release('viewer-3.9.0'),
        release('viewer-3.8.0')
      ], { headers: { Link: '<https://other.example/path>; rel="next"' } });
    }
    return Response.json([release('viewer-3.10.0'), release('viewer-3.7.0')]);
  } });
  assert.deepEqual(await checker.check(), { tag: 'viewer-3.10.0', version: '3.10.0' });
  assert.deepEqual(requests, [1, 2].map(page => `${VIEWER_RELEASES_API}?per_page=100&page=${page}`));
});

test('release checkers restore their own product caches from shared storage', async () => {
  const { createReleaseChecker, RELEASE_API } = loadRelease();
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  const fetch = async url => url === RELEASE_API
    ? Response.json(release('9.0.0'))
    : Response.json([release('viewer-3.0.0')]);
  const ctl = createReleaseChecker({ channel: 'ctl', storage, fetch });
  const viewer = createReleaseChecker({ channel: 'viewer', storage, fetch });
  await Promise.all([ctl.check(), viewer.check()]);
  assert.deepEqual(createReleaseChecker({ channel: 'ctl', storage, fetch }).cached(), { tag: '9.0.0', version: '9.0.0' });
  assert.deepEqual(createReleaseChecker({ channel: 'viewer', storage, fetch }).cached(), { tag: 'viewer-3.0.0', version: '3.0.0' });
});

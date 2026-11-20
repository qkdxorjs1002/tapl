const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const path = require('node:path');
const { buildSync } = require('esbuild');

function compile(entry, external = []) {
  return buildSync({ entryPoints: [path.join(__dirname, '../src', entry)], external,
    bundle: true, platform: 'node', format: 'cjs', write: false }).outputFiles[0].text;
}

function load(source) {
  const compiled = new Module(__filename, module);
  compiled.filename = __filename;
  compiled.paths = module.paths;
  compiled._compile(source, __filename);
  return compiled.exports;
}

const hostSource = compile('extension.ts', ['vscode', './taplMcpClient']);
const { compareTourVersions, isStableTourVersion, mergeTourHistory, normalizeTourHistory,
  TOUR_HISTORY_KEY } = load(compile('viewer/tourHistory.ts'));

function createHost(t, globalState) {
  const events = [], messages = [], calls = [], panels = [], commands = new Map(), subscriptions = [];
  const disposable = { dispose() {} };
  const workspace = { name: 'viewer', uri: { fsPath: '/work/tapl-tour-host' } };
  let hold, dropTourOpen = false;
  const vscode = {
    Uri: { joinPath(_base, ...parts) { return parts.join('/'); } },
    TreeItem: class {}, RelativePattern: class {}, EventEmitter: class { event() {} fire() {} },
    TreeItemCollapsibleState: { None: 0 }, ViewColumn: { One: 1 }, env: { language: 'en' },
    window: {
      registerTreeDataProvider() { return disposable; },
      createWebviewPanel() {
        const panel = {
          title: '', visible: true, reveals: 0,
          reveal() { this.reveals++; this.visible = true; },
          onDidDispose(fn) { this.close = fn; return disposable; },
          onDidChangeViewState(fn) { this.changed = fn; return disposable; },
          webview: {
            html: '', cspSource: 'test:', asWebviewUri(uri) { return uri; },
            onDidReceiveMessage(fn) { panel.receive = fn; return disposable; },
            async postMessage(message) {
              if (message.type === 'tour:open' && dropTourOpen) { dropTourOpen = false; return false; }
              events.push(message.type);
              messages.push(message);
              return true;
            }
          }
        };
        panels.push(panel);
        return panel;
      }
    },
    workspace: {
      workspaceFolders: [workspace],
      onDidChangeWorkspaceFolders() { return disposable; },
      createFileSystemWatcher() {
        return { ...disposable, onDidChange() { return disposable; }, onDidCreate() { return disposable; }, onDidDelete() { return disposable; } };
      }
    },
    commands: { registerCommand(name, fn) { commands.set(name, fn); return disposable; } }
  };
  class Pool {
    invalidate() {}
    async dispose() {}
    async callTool(_workspace, name) {
      calls.push(name);
      events.push(name);
      if (name === 'tapl_get_status') {
        const heldRead = hold;
        hold = undefined;
        if (heldRead) { heldRead.enter(); await heldRead.wait; }
        return { tasks: [], plans: [], findings: [] };
      }
      if (name === 'tapl_list_archives') return { archives: [] };
      throw new Error(`Unexpected tool: ${name}`);
    }
  }

  const originalLoad = Module._load;
  let extension;
  try {
    Module._load = function(name, ...args) {
      if (name === 'vscode') return vscode;
      if (name === './taplMcpClient') return { TaplMcpClientPool: Pool, taplMcpCommandCandidates: () => ['tapl-mcp'] };
      return originalLoad.call(this, name, ...args);
    };
    extension = load(hostSource);
    extension.activate({ extensionUri: 'extension', subscriptions, globalState });
  } finally { Module._load = originalLoad; }

  t.after(async () => { subscriptions.forEach(value => value.dispose()); await extension.deactivate(); });
  return {
    calls, events, messages, panels,
    showTour: () => commands.get('taplWorkflow.showTour')(),
    ready: () => panels.at(-1).receive({ command: 'ready' }),
    save: history => panels.at(-1).receive({ command: 'saveTourHistory', history }),
    dropNextTourOpen() { dropTourOpen = true; },
    holdNextStatus() {
      let enter, release;
      const wait = new Promise(resolve => { release = resolve; });
      const entered = new Promise(resolve => { enter = resolve; });
      hold = { enter, wait };
      return { entered, release };
    }
  };
}

test('tour release history is validated and merges progress by semantic version', () => {
  const ascending = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta', '1.0.0-beta',
    '1.0.0-beta.2', '1.0.0-beta.11', '1.0.0-rc.1', 'v1.0.0', '1.10.0'];
  for (let index = 1; index < ascending.length; index++) {
    assert.equal(compareTourVersions(ascending[index - 1], ascending[index]), -1);
    assert.equal(compareTourVersions(ascending[index], ascending[index - 1]), 1);
  }
  assert.equal(compareTourVersions('v1.0.0+first', '1.0.0+second'), 0);
  assert.equal(compareTourVersions('9007199254740993.0.0', '9007199254740992.0.0'), 1);
  assert.equal(compareTourVersions('1.0.0-01', '1.0.0'), undefined);
  assert.equal(compareTourVersions('1.0.0\n', '1.0.0'), undefined);
  assert.equal(isStableTourVersion('v1.0.0+build.2'), true);
  assert.equal(isStableTourVersion('1.0.0-beta.1'), false);
  assert.deepEqual(normalizeTourHistory({ intro: 'began', releaseSeenThrough: { version: '1.0.0' } }), {});
  const completed = { intro: 'completed', releaseSeenThrough: '1.0.0' };
  const dismissed = { intro: 'dismissed', releaseSeenThrough: 'v1.1.0+build.2', extra: 'ignored' };
  const merged = { intro: 'completed', releaseSeenThrough: '1.1.0' };
  assert.deepEqual(mergeTourHistory(completed, dismissed), merged);
  assert.deepEqual(mergeTourHistory(dismissed, completed), merged);
});

test('the palette command queues one open through duplicate readiness and reveals the existing panel', async t => {
  const host = createHost(t, { get: () => ({ intro: 'dismissed' }) });
  await host.showTour();
  await host.showTour();
  const panel = host.panels[0];
  assert.equal(host.panels.length, 1);
  assert.match(panel.webview.html, /webview-dist\/assets\/index.js/);
  assert.deepEqual(host.events, []);

  const firstRead = host.holdNextStatus();
  const firstReady = host.ready();
  await firstRead.entered;
  assert.deepEqual(host.events, ['tour:history', 'tapl_get_status']);
  assert.deepEqual(host.messages[0], { type: 'tour:history', history: { intro: 'dismissed' } });
  await host.ready();
  firstRead.release();
  await firstReady;
  assert.deepEqual(host.messages.map(({ type }) => type), ['tour:history', 'tour:history', 'hydrate', 'tour:open']);

  const reads = host.calls.length;
  panel.visible = false;
  await host.showTour();
  assert.equal(host.panels.length, 1);
  assert.equal(panel.reveals, 2);
  assert.equal(host.messages.at(-1).type, 'tour:open');
  assert.equal(host.calls.length, reads);

  host.dropNextTourOpen();
  const count = host.messages.length;
  await host.showTour();
  assert.equal(host.messages.length, count);
  panel.changed();
  assert.equal(host.messages.length, count + 1);
  assert.equal(host.messages.at(-1).type, 'tour:open');
});

test('profile saves ignore malformed data, serialize updates and rehydrate persistently', async t => {
  const writes = [];
  let stored = { intro: 'dismissed', releaseSeenThrough: '2.9.0' };
  let allowFirstWrite, signalFirstWrite;
  const firstWrite = new Promise(resolve => { allowFirstWrite = resolve; });
  const firstWriteStarted = new Promise(resolve => { signalFirstWrite = resolve; });
  const globalState = {
    get(key) { assert.equal(key, TOUR_HISTORY_KEY); return stored; },
    async update(key, value) {
      assert.equal(key, TOUR_HISTORY_KEY);
      writes.push(value);
      if (writes.length === 1) { signalFirstWrite(); await firstWrite; }
      stored = value;
    }
  };
  const host = createHost(t, globalState);
  await host.showTour();
  await host.ready();
  const reads = host.calls.length;
  for (const payload of [null, [], 'dismissed', { intro: 'open', releaseSeenThrough: 'invalid' }, { optional: 'ignored' }]) {
    await host.save(payload);
  }
  assert.deepEqual(writes, []);

  const first = host.save({ releaseSeenThrough: 'v2.10.0' });
  await firstWriteStarted;
  const second = host.save({ intro: 'completed', releaseSeenThrough: '2.11.0-beta.1', extra: 42 });
  assert.deepEqual(writes, [{ intro: 'dismissed', releaseSeenThrough: '2.10.0' }]);
  allowFirstWrite();
  await Promise.all([first, second]);
  await host.save({ intro: 'dismissed', releaseSeenThrough: '1.0.0' });
  assert.deepEqual(writes, [{ intro: 'dismissed', releaseSeenThrough: '2.10.0' },
    { intro: 'completed', releaseSeenThrough: '2.11.0-beta.1' }]);
  assert.equal(host.calls.length, reads);

  const restartedHost = createHost(t, globalState);
  await restartedHost.showTour();
  await restartedHost.ready();
  assert.deepEqual(restartedHost.messages[0], { type: 'tour:history', history: stored });
});

test('missing or failing profile storage falls back to in-memory progress across panels', async t => {
  for (const globalState of [undefined, {
    get() { throw new Error('Storage unavailable'); },
    async update() { throw new Error('Storage unavailable'); }
  }]) {
    const host = createHost(t, globalState);
    await host.showTour();
    await host.ready();
    assert.deepEqual(host.messages[0], { type: 'tour:history', history: {} });
    await host.save({ intro: 'dismissed', releaseSeenThrough: '1.2.3' });
    const firstPanel = host.panels[0];
    firstPanel.close();
    await firstPanel.receive({ command: 'saveTourHistory', history: { releaseSeenThrough: '99.0.0' } });
    await host.showTour();
    await host.ready();
    assert.deepEqual(host.messages.findLast(({ type }) => type === 'tour:history'),
      { type: 'tour:history', history: { intro: 'dismissed', releaseSeenThrough: '1.2.3' } });
  }
});

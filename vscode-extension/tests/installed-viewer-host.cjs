const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');

function load(entry, modules = {}) {
  const source = buildSync({ entryPoints: [path.join(__dirname, '../src', entry)], bundle: true,
    platform: 'node', format: 'cjs', write: false, packages: 'external', external: Object.keys(modules) }).outputFiles[0].text;
  const mod = new Module(__filename, module);
  mod.filename = __filename;
  mod.paths = module.paths;
  const original = mod.require;
  mod.require = function (name) { return modules[name] ?? original.call(this, name); };
  mod._compile(source, __filename);
  return mod.exports;
}

function install(t) {
  const temp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'tapl-host-install-')));
  t.after(() => fs.rmSync(temp, { recursive: true, force: true }));
  const root = path.join(temp, 'pkg with space', 'taplctl', '_viewer'), assets = path.join(root, 'assets');
  fs.mkdirSync(assets, { recursive: true });
  for (const name of ['index.css', 'index.js']) fs.writeFileSync(path.join(assets, name), 'fixture');
  return { temp, assets, bundle: { ok: true, asset_root: root, protocol: 1, ctl_version: '2.27.0' } };
}

test('bundle resolution requires both Viewer tools, protocol and files in the installed package', async t => {
  const { installedViewerBundle } = load('viewerInstall.ts');
  const { bundle, assets, temp } = install(t);
  const tools = new Set(['tapl_viewer_dispatch', 'tapl_viewer_get_bundle']);
  let descriptor = bundle, calls = 0;
  const clients = {
    async supportsTool(_, name) { return tools.has(name); },
    async callTool(_, name, args) {
      calls++; assert.equal(name, 'tapl_viewer_get_bundle'); assert.deepEqual(args, {}); return descriptor;
    }
  };
  const discover = () => installedViewerBundle(clients, { cwd: temp, key: temp, commands: ['trusted-mcp'] });
  assert.deepEqual(await discover(), { assets, version: bundle.ctl_version });
  tools.delete('tapl_viewer_dispatch');
  assert.equal(await discover(), undefined);
  assert.equal(calls, 1);
  tools.add('tapl_viewer_dispatch');
  for (const invalid of [{ protocol: 2 }, { asset_root: '.' }, { asset_root: temp }, { ctl_version: '' }, { ok: false }]) {
    descriptor = { ...bundle, ...invalid };
    assert.equal(await discover(), undefined);
  }
  descriptor = bundle;
  const entry = path.join(assets, 'index.js');
  fs.renameSync(entry, path.join(temp, 'outside'));
  fs.symlinkSync(path.join(temp, 'outside'), entry);
  assert.equal(await discover(), undefined);
  fs.unlinkSync(entry);
  fs.writeFileSync(entry, 'fixture');
  fs.renameSync(assets, path.join(temp, 'external-assets'));
  fs.symlinkSync(path.join(temp, 'external-assets'), assets, 'dir');
  assert.equal(await discover(), undefined);
});

class Uri {
  constructor(fsPath, scheme = 'file', authority = '') { this.path = this.fsPath = fsPath; this.scheme = scheme; this.authority = authority; }
  with({ path }) { return new Uri(path, this.scheme, this.authority); }
  static file(name) { return new Uri(name); }
  static joinPath(base, ...parts) { return base.with({ path: path.join(base.path, ...parts) }); }
}

test('native shell proxies to the selected installation, resets multi-root state, and negotiates each reopen', async t => {
  const { temp, assets, bundle } = install(t);
  const commands = new Map(), subscriptions = [], panels = [], calls = [], invalidations = [], watchers = [];
  const roots = ['first', 'second'].map(name => {
    const fsPath = path.join(temp, name); fs.mkdirSync(path.join(fsPath, '.tapl'), { recursive: true });
    fs.writeFileSync(path.join(fsPath, '.tapl', 'config.toml'), '[viewer]\nmcp_path="trusted-mcp"');
    return { name, uri: new Uri(fsPath, 'vscode-remote', 'ssh-host') };
  });
  let version = 'new', search = 'records', releaseWrite, startedWrite;
  const writeStarted = new Promise(resolve => { startedWrite = resolve; });
  const disposable = { dispose() {} };
  const vscode = { Uri, TreeItem: class {}, EventEmitter: class { event() {} fire() {} },
    RelativePattern: class { constructor(root, pattern) { this.root = root; this.pattern = pattern; } },
    ViewColumn: { One: 1 }, env: { language: 'ko' },
    commands: { registerCommand(name, fn) { commands.set(name, fn); return disposable; } },
    workspace: { workspaceFolders: roots, isTrusted: true, onDidChangeWorkspaceFolders() { return disposable; },
      createFileSystemWatcher(pattern) {
        const watcher = { ...disposable, pattern, onDidChange(fn) { this.change = fn; return disposable; },
          onDidCreate() { return disposable; }, onDidDelete() { return disposable; } };
        watchers.push(watcher); return watcher;
      } },
    window: { registerTreeDataProvider() { return disposable; }, showInputBox() { return search; },
      showWorkspaceFolderPick() { return roots[1]; }, createWebviewPanel(type, title, column, options) {
        assert.equal(type, 'taplWorkflow.viewer'); assert.deepEqual(options.localResourceRoots, []);
        const panel = { title, messages: [], visible: true, reveal() {}, onDidDispose(fn) { this.close = fn; },
          webview: { html: '', cspSource: 'https://viewer.invalid',
            asWebviewUri(uri) { assert.equal(uri.authority, 'ssh-host'); return 'webview://ssh-host' + uri.path.split(path.sep).join('/'); },
            onDidReceiveMessage(fn) { panel.receive = fn; }, async postMessage(msg) { panel.messages.push(msg); return true; } } };
        panels.push(panel); return panel;
      } } };
  class Pool {
    invalidate(key) { invalidations.push(key); }
    async dispose() {}
    async supportsTool(_, name) { return version === 'new' && ['tapl_viewer_get_bundle', 'tapl_viewer_dispatch'].includes(name); }
    async callTool(workspace, name, args) {
      calls.push({ workspace, name, args });
      if (name === 'tapl_viewer_get_bundle') return bundle;
      if (name === 'tapl_viewer_dispatch') {
        assert.equal(args.protocol, 1); assert.equal(args.message.locale, 'ko');
        if (args.message.command === 'saveSettings') {
          startedWrite(); await new Promise(resolve => { releaseWrite = resolve; });
          return { type: 'settings:result', ok: true, workspace: workspace.cwd, requestId: args.message.requestId };
        }
        return { type: 'hydrate', workspace: workspace.cwd, view: { type: 'overview', status: { active_run: null } } };
      }
      if (name === 'tapl_get_status') return { tasks: [], plans: [], findings: [] };
      if (name === 'tapl_list_archives') return { archives: [] };
      assert.fail(name);
    }
  }
  const extension = load('extension.ts', { vscode, './taplMcpClient': {
    TaplMcpClientPool: Pool, taplMcpCommandCandidates: configured => [configured]
  } });
  extension.activate({ extensionUri: new Uri('/extension', 'vscode-remote', 'ssh-host'), subscriptions });
  t.after(async () => { subscriptions.forEach(item => item.dispose()); await extension.deactivate(); });
  const open = name => commands.get('taplWorkflow.' + name)();
  const channelOf = panel => panel.webview.html.match(/name="tapl-viewer-channel" content="([0-9a-f]{32})"/)?.[1];

  await open('search');
  const panel = panels[0], channel = channelOf(panel);
  assert.ok(channel); assert.match(panel.webview.html, /name="tapl-viewer-protocol" content="1"/);
  assert.ok(panel.webview.html.includes(assets.split(path.sep).join('/') + '/index.js'));
  assert.deepEqual(panel.webview.options.localResourceRoots, [new Uri(assets, 'vscode-remote', 'ssh-host')]);
  const request = (requestId, message, extra) => panel.receive({ command: 'viewerRequest', protocol: 1, channel, requestId, message, ...extra });
  await open('showTour');
  await request('1', { command: 'ready', workspace: '' });
  assert.deepEqual(panel.messages.map(x => x.type), ['tour:history', 'viewer:response', 'tour:open', 'viewer:navigate']);
  assert.equal(panel.messages[1].payload.workspace, roots[0].uri.fsPath);
  assert.deepEqual(panel.messages.at(-1).message, { command: 'search', query: search });
  const before = calls.length;
  await request('2', { command: 'discardRun' }, { channel: 'obsolete' });
  await request('2', { command: 'discardRun' }, { protocol: 7 });
  await panel.receive({ command: 'discardRun', workspace: roots[0].uri.fsPath });
  assert.equal(calls.length, before);
  const future = { command: 'futureCtlCommand', source_db: 'tapl-peer.db', futureField: 42 };
  await request('3', future);
  assert.deepEqual(calls.at(-1).args.message, { ...future, locale: 'ko' });
  assert.equal(panel.messages.at(-1).requestId, '3');
  await panel.receive({ command: 'chooseWorkspace' });
  assert.deepEqual(panel.messages.at(-1), { type: 'viewer:navigate', channel, message: { command: 'ready' }, reset: true });
  await request('4', { command: 'ready', workspace: '' });
  assert.equal(panel.messages.at(-1).payload.workspace, roots[1].uri.fsPath);
  await open('refresh');
  assert.deepEqual(panel.messages.at(-1).message, { command: 'refresh' });
  const write = request('5', { command: 'saveSettings', workspace: roots[1].uri.fsPath, requestId: 'edit' });
  await writeStarted;
  watchers.find(w => w.pattern.root === roots[1] && w.pattern.pattern === '.tapl/config.toml').change();
  assert.deepEqual(invalidations, []);
  releaseWrite(); await write;
  assert.equal(panel.messages.find(msg => msg.requestId === '5').payload.ok, true);
  assert.deepEqual(invalidations, [undefined]);
  await open('refresh');
  panel.close();
  version = 'old';
  await open('openOverview');
  assert.equal(invalidations.at(-1), roots[1].uri.fsPath);
  assert.equal(channelOf(panels[1]), undefined); assert.match(panels[1].webview.html, /webview-dist\/assets\/index.js/);
  assert.equal(panels[1].messages.at(-1).view.type, 'overview');
  panels[1].close();
  version = 'new'; await open('openOverview');
  assert.ok(channelOf(panels[2])); assert.notEqual(channelOf(panels[2]), channel);
});

test('a lost generic dispatch acknowledgement never replays the request', async () => {
  const { WorkspaceTaplMcpClient } = load('taplMcpClient.ts');
  let calls = 0, connections = 0;
  const client = new WorkspaceTaplMcpClient({ key: 'one', cwd: '/workspace', commands: ['mcp'] }, {
    createClient() { connections++; return { async connect() {}, async close() {},
      async listTools() { return { tools: [{ name: 'tapl_viewer_dispatch' }] }; },
      async callTool() { calls++; throw new Error('lost acknowledgement'); } }; },
    createTransport() { return {}; }
  });
  try {
    await assert.rejects(client.callTool('tapl_viewer_dispatch', { protocol: 1, message: { command: 'discardRun' } }), /lost acknowledgement/);
    assert.equal(calls, 1); assert.equal(connections, 1);
    assert.equal(await client.supportsTool('tapl_viewer_dispatch'), true);
    assert.equal(connections, 2);
  } finally { await client.dispose(); }
});

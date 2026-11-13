const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { buildSync } = require('esbuild');
const output = buildSync({ entryPoints: [path.join(__dirname, '../src/extension.ts')], bundle: true, write: false,
  platform: 'node', format: 'cjs', external: ['vscode', './taplMcpClient'] }).outputFiles[0].text;
const tick = () => new Promise(resolve => setImmediate(resolve));
const settings = { path: '/work/first/config.toml', exists: true, revision: 'r1', fields: [], values: {}, defaults: {}, overrides: {} };

test('VS Code settings bind workspace without a RUN, validate mutations and keep navigation separate', async () => {
  const calls = [], messages = [], commands = new Map(), disposable = { dispose() {} };
  const folders = ['first', 'second'].map(name => ({ name, uri: { fsPath: `/work/${name}` } }));
  let receive, disposePanel, delayed, slow = false, unsupported = false, currentSettings = settings;
  const panel = { title: '', reveal() {}, onDidDispose(fn) { disposePanel = fn; return disposable; }, webview: {
    html: '', cspSource: 'test:', asWebviewUri(uri) { return uri; }, onDidReceiveMessage(fn) { receive = fn; return disposable; },
    async postMessage(message) { messages.push(message); return true; }
  } };
  const vscode = {
    Uri: { joinPath(_base, ...parts) { return parts.join('/'); } }, TreeItem: class {}, ThemeIcon: class {}, RelativePattern: class {},
    EventEmitter: class { event() {} fire() {} }, TreeItemCollapsibleState: { None: 0 }, ViewColumn: { One: 1 },
    window: { registerTreeDataProvider() { return disposable; }, createWebviewPanel() { return panel; },
      async showWarningMessage() {}, async showWorkspaceFolderPick() { return folders[1]; } },
    workspace: { workspaceFolders: folders, getConfiguration() { return { get(_key, fallback) { return fallback; } }; },
      onDidChangeConfiguration() { return disposable; }, onDidChangeWorkspaceFolders() { return disposable; },
      createFileSystemWatcher() { return { ...disposable, onDidChange() { return disposable; }, onDidCreate() { return disposable; }, onDidDelete() { return disposable; } }; } },
    commands: { registerCommand(name, fn) { commands.set(name, fn); return disposable; }, async executeCommand(name) { return commands.get(name)?.(); } }, env: { language: 'en' }
  };
  class Pool {
    invalidate() {} async dispose() {}
    async callTool(workspace, name, args) {
      calls.push({ root: workspace.cwd, name, args: { ...args } });
      if (name === 'tapl_get_status') return { session_id: args.session_id ?? '', active_run: null, active_runs: [], tasks: [], plans: [], findings: [], viewer_capabilities: {} };
      if (name === 'tapl_list_archives') return { archives: [] };
      if (name === 'tapl_get_run') return { run: { id: args.run_id, status: 'archived', source_db: args.source_db } };
      if (name === 'tapl_get_settings' || name === 'tapl_save_settings') {
        if (slow) await new Promise(resolve => { delayed = resolve; });
        if (unsupported) throw new Error('Unknown tool tapl_get_settings');
        if (name === 'tapl_save_settings') currentSettings = { ...settings, revision: 'r2' };
        return { ok: true, settings: currentSettings, changed: name === 'tapl_save_settings' };
      }
      throw new Error(`Unexpected tool ${name}`);
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
    const mod = new Module(path.join(__dirname, 'settings-host-virtual.cjs'), module);
    mod.filename = path.join(__dirname, 'settings-host-virtual.cjs'); mod.paths = module.paths; mod._compile(output, mod.filename);
    extension = mod.exports; extension.activate({ extensionUri: 'extension', subscriptions: [] });
  } finally { Module._load = originalLoad; }
  const send = async message => { await receive(message); return messages.at(-1); };
  await commands.get('taplWorkflow.openOverview')();
  await send({ command: 'selectRun', sessionId: 'archived-owner', source_db: 'peer.db' });
  await send({ command: 'openRun', runId: 'archived', source_db: 'peer.db' });
  const get = { command: 'getSettings', requestId: 'get', workspace: '/work/first' };
  const save = { command: 'saveSettings', requestId: 'save', workspace: '/work/first', revision: 'r1', values: { 'logging.enabled': false } };
  assert.equal((await send(get)).ok, true);
  assert.equal(messages.at(-1).type, 'settings:result');
  assert.deepEqual(calls.find(call => call.name === 'tapl_get_settings'), { name: 'tapl_get_settings', root: '/work/first', args: {} });
  const before = calls.length;
  for (const invalid of [{ workspace: '/work/second' }, { revision: 'old' }, { values: [] }]) assert.equal((await send({ ...save, ...invalid })).ok, false);
  assert.equal((await send({ command: 'resetSettings', requestId: 'reset', workspace: '/work/first', revision: 'r1', confirmed: false })).ok, false);
  assert.equal(calls.length, before);
  slow = true; receive({ ...get, requestId: 'stale-read' }); while (!delayed) await tick();
  const staleRead = delayed; delayed = undefined;
  receive({ ...get, requestId: 'latest-read' }); while (!delayed) await tick();
  delayed(); delayed = undefined; for (let i = 0; i < 8; i++) await tick();
  assert.equal(messages.at(-1).requestId, 'latest-read');
  const readCount = messages.length; staleRead(); for (let i = 0; i < 8; i++) await tick();
  assert.equal(messages.length, readCount);
  slow = true; receive(save); while (!delayed) await tick();
  assert.equal((await send({ ...save, requestId: 'concurrent' })).code, 'busy');
  await send({ command: 'openRun', runId: 'newer', source_db: 'peer.db' });
  delayed(); delayed = undefined; for (let i = 0; i < 8; i++) await tick();
  assert.equal(messages.at(-1).requestId, 'save');
  assert.equal(messages.findLast(message => message.view)?.view.snapshot.run.id, 'newer');
  assert.deepEqual(calls.find(call => call.name === 'tapl_save_settings').args, { expected_revision: 'r1', values: { 'logging.enabled': false } });
  slow = false;
  assert.equal((await send({ command: 'resetSettings', requestId: 'reset', workspace: '/work/first', revision: 'r2', confirmed: true })).ok, true);
  assert.deepEqual(calls.filter(call => call.name === 'tapl_save_settings').at(-1).args, { expected_revision: 'r2', values: {}, reset_all: true });
  unsupported = true;
  assert.equal((await send(get)).code, 'unsupported'); assert.match(messages.at(-1).message, /Update TAPL/);
  assert.equal(messages.findLast(message => message.view)?.view.snapshot.run.id, 'newer');
  unsupported = false; slow = true; receive(get); while (!delayed) await tick();
  await send({ command: 'chooseWorkspace' }); const switched = messages.length;
  delayed(); delayed = undefined; for (let i = 0; i < 8; i++) await tick();
  assert.equal(messages.length, switched);
  assert.equal(messages.at(-1).workspace, '/work/second');
  receive({ ...get, workspace: '/work/second' }); while (!delayed) await tick(); disposePanel();
  const closed = messages.length; delayed(); for (let i = 0; i < 8; i++) await tick(); assert.equal(messages.length, closed);
  await extension.deactivate();
});

function configHost(t, options = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'tapl-settings-host-'));
  const home = path.join(directory, 'home');
  const folders = ['first', 'second'].map(name => ({ name, uri: { fsPath: path.join(directory, name) } }));
  fs.mkdirSync(home); folders.forEach(folder => fs.mkdirSync(folder.uri.fsPath));
  const local = path.join(folders[0].uri.fsPath, '.tapl', 'config.toml'), user = path.join(home, '.tapl', 'config.toml');
  const write = (file, text) => { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, text); };
  options.prepare?.({ local, user, folders, write });
  const calls = [], messages = [], trace = [], watchers = [], commands = new Map();
  const disposable = { dispose() {} }, subscriptions = [];
  let receive, folderChanged, trustGranted, extension, revision = 'r1', invalidations = 0;
  const panel = { title: '', reveal() {}, onDidDispose() { return disposable; }, webview: {
    html: '', cspSource: 'test:', asWebviewUri(uri) { return uri; },
    onDidReceiveMessage(fn) { receive = fn; return disposable; },
    async postMessage(message) { messages.push(message); trace.push(`message:${message.requestId ?? message.type}`); return true; }
  } };
  const vscode = {
    Uri: { joinPath(_base, ...parts) { return parts.join('/'); } }, TreeItem: class {}, ThemeIcon: class {},
    RelativePattern: class { constructor(base, pattern) { this.base = typeof base === 'string' ? base : base.uri.fsPath; this.pattern = pattern; } },
    EventEmitter: class { event() {} fire() {} }, TreeItemCollapsibleState: { None: 0 }, ViewColumn: { One: 1 },
    window: { registerTreeDataProvider() { return disposable; }, createWebviewPanel() { return panel; },
      async showWorkspaceFolderPick() { return folders[1]; } },
    workspace: { workspaceFolders: folders, isTrusted: options.trusted ?? true,
      getConfiguration() { throw new Error('Old VS Code settings must never be read'); },
      onDidChangeWorkspaceFolders(fn) { folderChanged = fn; return disposable; },
      onDidGrantWorkspaceTrust(fn) { trustGranted = fn; return disposable; },
      createFileSystemWatcher(pattern) {
        const handlers = {}, watcher = { ...disposable, pattern, handlers,
          onDidChange(fn) { handlers.change = fn; return disposable; },
          onDidCreate(fn) { handlers.create = fn; return disposable; },
          onDidDelete(fn) { handlers.delete = fn; return disposable; } };
        watchers.push(watcher); return watcher;
      } },
    commands: { registerCommand(name, fn) { commands.set(name, fn); return disposable; }, async executeCommand(name) { return commands.get(name)?.(); } },
    env: { language: options.language ?? 'en' }
  };
  class Pool {
    invalidate() { invalidations++; trace.push('invalidate'); }
    async dispose() {}
    async callTool(workspace, name, args) {
      calls.push({ root: workspace.cwd, commands: [...workspace.commands], name, args }); trace.push(`tool:${name}`);
      if (name === 'tapl_get_status') return { active_run: null, tasks: [], plans: [], findings: [], viewer_capabilities: {} };
      if (name === 'tapl_list_archives') return { archives: [] };
      if (name === 'tapl_get_run') return { run: { id: args.run_id }, tasks: [], plans: [], findings: [] };
      if (name === 'tapl_save_settings') { await options.save?.(); revision = revision === 'r1' ? 'r2' : 'r3'; }
      if (name === 'tapl_get_settings' || name === 'tapl_save_settings') return {
        ok: true, settings: { ...settings, path: local, revision }, changed: name === 'tapl_save_settings'
      };
      throw new Error(`Unexpected tool ${name}`);
    }
  }
  const originalLoad = Module._load;
  try {
    Module._load = function(name, ...args) {
      if (name === 'vscode') return vscode;
      if (name === 'node:os') return { ...os, homedir: () => home };
      if (name === './taplMcpClient') return { TaplMcpClientPool: Pool,
        taplMcpCommandCandidates: value => value === '' ? ['tapl-mcp'] : [value] };
      return originalLoad.call(this, name, ...args);
    };
    const mod = new Module(path.join(__dirname, 'settings-config-host-virtual.cjs'), module);
    mod.filename = path.join(__dirname, 'settings-config-host-virtual.cjs'); mod.paths = module.paths; mod._compile(output, mod.filename);
    extension = mod.exports; extension.activate({ extensionUri: 'extension', subscriptions });
  } finally { Module._load = originalLoad; }
  t.after(async () => { subscriptions.forEach(item => item.dispose()); await extension.deactivate(); fs.rmSync(directory, { recursive: true, force: true }); });
  const flush = async () => { for (let i = 0; i < 10; i++) await tick(); };
  const send = async message => { receive(message); await flush(); return message.requestId
    ? messages.findLast(reply => reply.requestId === message.requestId) : messages.at(-1); };
  const fire = (file, event = 'change') => {
    const watcher = watchers.find(item => path.join(item.pattern.base, item.pattern.pattern) === file);
    assert.ok(watcher, `Expected config watcher for ${file}`); watcher.handlers[event]({ fsPath: file });
  };
  return { local, user, folders, write, calls, messages, trace, watchers, vscode, commands, send, flush, fire,
    receive: message => receive(message), workspaceChanged: () => folderChanged(), grantTrust: () => trustGranted(),
    invalidations: () => invalidations };
}

test('host bootstraps custom command before MCP and follows file creation/deletion, auto locale and workspace changes', async t => {
  const h = configHost(t, { language: 'ko-KR', prepare({ user, write }) {
    write(user, '[viewer]\nlanguage="en"\nlayout="large"\nmcp_path="/a directory/custom-mcp"');
  } });
  await h.commands.get('taplWorkflow.openOverview')();
  assert.deepEqual(h.calls[0].commands, ['/a directory/custom-mcp']);
  assert.equal(h.messages.at(-1).locale, 'en'); assert.equal(h.messages.at(-1).layout, 'large');
  assert.deepEqual(h.messages.at(-1).preferences, { language: 'en', layout: 'large', mcp_path: '/a directory/custom-mcp' });
  h.write(h.local, '[viewer]\nlayout="medium"'); h.fire(h.local, 'create'); await h.flush();
  assert.equal(h.messages.at(-1).locale, 'ko'); assert.equal(h.messages.at(-1).layout, 'medium');
  assert.deepEqual(h.calls.at(-1).commands, ['tapl-mcp']);
  fs.unlinkSync(h.local); h.fire(h.local, 'delete'); await h.flush();
  assert.equal(h.messages.at(-1).locale, 'en'); assert.equal(h.messages.at(-1).layout, 'large');
  h.write(h.user, '[viewer]\nlanguage="ko"'); h.fire(h.user); await h.flush();
  assert.equal(h.messages.at(-1).locale, 'ko'); assert.equal(h.messages.at(-1).layout, 'auto');
  const secondConfig = path.join(h.folders[1].uri.fsPath, '.tapl', 'config.toml');
  h.write(secondConfig, '[viewer]\nlanguage="en"\nlayout="small"');
  await h.send({ command: 'chooseWorkspace' });
  assert.equal(h.messages.at(-1).workspace, h.folders[1].uri.fsPath);
  assert.equal(h.messages.at(-1).locale, 'en'); assert.equal(h.messages.at(-1).layout, 'small');
});

test('host blocks malformed selected configuration and untrusted workspace executables without fallback', async t => {
  const h = configHost(t, { trusted: false, prepare({ local, user, write }) {
    write(user, '[viewer]\nmcp_path="user-mcp"'); write(local, '[viewer]\nlanguage="invalid"');
  } });
  await h.commands.get('taplWorkflow.openOverview')();
  assert.equal(h.calls.length, 0); assert.equal(h.messages.at(-1).view.type, 'error');
  assert.match(h.messages.at(-1).view.message, /viewer.language/);
  h.write(h.local, '[viewer]\nmcp_path="workspace-mcp"'); h.fire(h.local); await h.flush();
  assert.equal(h.calls.length, 0); assert.match(h.messages.at(-1).view.message, /Trust this workspace/);
  h.vscode.workspace.isTrusted = true; h.grantTrust(); await h.flush();
  assert.deepEqual(h.calls.at(-1).commands, ['workspace-mcp']);
  h.vscode.workspace.isTrusted = false; fs.unlinkSync(h.local); h.fire(h.local, 'delete'); await h.flush();
  assert.match(h.messages.at(-1).view.message, /Trust this workspace/);
  const executable = path.resolve('/trusted/user-mcp');
  h.write(h.user, `[viewer]\nmcp_path=${JSON.stringify(executable)}`); h.fire(h.user); await h.flush();
  assert.deepEqual(h.calls.at(-1).commands, [executable]);
});

test('save watcher refresh waits for acknowledgement and result metadata applies saved and reset preferences', async t => {
  let release;
  const options = { prepare({ local, write }) { write(local, '[viewer]\nlanguage="en"\nmcp_path="old-mcp"'); } };
  const h = configHost(t, options), workspace = h.folders[0].uri.fsPath;
  await h.commands.get('taplWorkflow.openOverview')();
  await h.send({ command: 'getSettings', requestId: 'get', workspace });
  options.save = async () => {
    h.write(h.local, '[viewer]\nlanguage="ko"\nlayout="large"\nmcp_path="/new executable/mcp"');
    h.fire(h.local); await new Promise(resolve => { release = resolve; });
  };
  const baseline = h.invalidations();
  h.receive({ command: 'saveSettings', requestId: 'save', workspace, revision: 'r1', values: { 'viewer.language': 'ko' } });
  await h.flush(); assert.equal(typeof release, 'function'); assert.equal(h.invalidations(), baseline);
  await h.send({ command: 'openRun', runId: 'newer' });
  assert.deepEqual(h.calls.at(-1).commands, ['old-mcp']);
  assert.equal((await h.send({ command: 'getSettings', requestId: 'busy', workspace })).code, 'busy');
  release(); await h.flush();
  const saved = h.messages.findLast(message => message.requestId === 'save');
  assert.equal(saved.ok, true); assert.equal(saved.locale, 'ko'); assert.equal(saved.layout, 'large');
  assert.deepEqual(saved.preferences, { language: 'ko', layout: 'large', mcp_path: '/new executable/mcp' });
  assert.ok(h.trace.indexOf('invalidate') > h.trace.indexOf('message:save'));
  assert.deepEqual(h.calls.at(-1).commands, ['/new executable/mcp']);
  options.save = async () => { h.write(h.local, ''); h.fire(h.local); };
  const reset = await h.send({ command: 'resetSettings', requestId: 'reset', workspace, revision: 'r2', confirmed: true });
  assert.equal(reset.ok, true); assert.equal(reset.locale, 'en'); assert.equal(reset.layout, 'auto');
  assert.deepEqual(reset.preferences, { language: 'auto', layout: 'auto', mcp_path: '' });
});

const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');

test('extension uses the shared read-only Viewer protocol and reloads current routes', async () => {
  const calls = [], messages = [], commands = new Map(), watchedPatterns = [];
  let receive, disposed, revision = 1, deleted = false, oldServer = false, delayed, foldersChanged, watcherCount = 0, unavailable = false, itemSource = false, multiRun = false;
  let diagnostics = { stored_count: 80, matched_count: 51, last_capture_error: {
    run_id: 'r1', slot: 2, code: 'invalid_memory_note', message: '<script>capture failed</script>', created_at: '2026-09-16T00:00:00Z'
  } };
  const disposable = { dispose() {} };
  const folder = (name) => ({ name, uri: { fsPath: `/work/${name}` } });
  const folders = [folder('first'), folder('second')];
  const memory = () => ({ id: 'm1', note: `Memory ${revision}`, source_available: true,
    source_record: itemSource ? { kind: 'item', item: { id: 1 } } : { kind: 'run', run: { id: 'r1', result_summary: `Result ${revision}` } } });
  const panel = { title: '', reveal() {}, onDidDispose(fn) { disposed = fn; return disposable; },
    webview: { html: '', cspSource: 'test:', asWebviewUri(uri) { return uri; },
      onDidReceiveMessage(fn) { receive = fn; return disposable; },
      async postMessage(message) { messages.push(message); return true; } } };
  const vscode = {
    Uri: { joinPath(_base, ...parts) { return parts.join('/'); } },
    TreeItem: class {}, ThemeIcon: class {}, RelativePattern: class { constructor(_root, pattern) { this.pattern = pattern; } },
    EventEmitter: class { event() {} fire() {} }, TreeItemCollapsibleState: { None: 0 }, ViewColumn: { One: 1 },
    window: { registerTreeDataProvider() { return disposable; }, createWebviewPanel() { return panel; },
      async showWarningMessage() {}, async showWorkspaceFolderPick() { return folders[1]; } },
    workspace: { workspaceFolders: folders, getConfiguration() { return { get(_key, fallback) { return fallback; } }; },
      onDidChangeConfiguration() { return disposable; },
      onDidChangeWorkspaceFolders(fn) { foldersChanged = fn; return disposable; },
      createFileSystemWatcher(pattern) { watchedPatterns.push(pattern.pattern); watcherCount++; return { ...disposable, onDidChange() { return disposable; }, onDidCreate() { return disposable; }, onDidDelete() { return disposable; } }; } },
    commands: { registerCommand(name, fn) { commands.set(name, fn); return disposable; }, async executeCommand(name) { return commands.get(name)?.(); } },
    env: { language: 'en' }
  };
  class Pool {
    invalidate() {}
    async callTool(workspace, name, args) {
      calls.push({ root: workspace.cwd, name, args });
      if (name === 'tapl_get_status' && unavailable) throw new Error('No TAPL database');
      if (name === 'tapl_get_status' && multiRun) return {
        active_runs: [{ id: 'ra', session_id: 'session-a' }, { id: 'rb', session_id: 'session-b' }],
        active_run: args.session_id ? { id: args.session_id === 'session-a' ? 'ra' : 'rb', session_id: args.session_id } : null,
        session_id: args.session_id ?? '', tasks: [{ id: 11, stable_id: 'TASK-001', active_execution: { execution_id: 'execution-a' }, depends_on: ['TASK-002'] }], findings: [],
        plans: args.session_id ? [{ stable_id: 'PLAN-001', title: args.session_id }] : []
      };
      if (name === 'tapl_get_status') return { active_run: null, tasks: [], plans: [], findings: [],
        viewer_capabilities: oldServer ? undefined : { associativeMemory: true } };
      if (name === 'tapl_list_archives') return { archives: [] };
      if (name === 'tapl_recall') {
        if (args.query === 'slow') await new Promise(resolve => { delayed = resolve; });
        return { total: 51, memories: [memory()], ...(diagnostics ? { diagnostics } : {}) };
      }
      if (name === 'tapl_get_memory') return { memory: deleted ? null : { ...memory(), ...(args.source_db ? { source_db: args.source_db } : {}) } };
      if (name === 'tapl_get_item') return { item: { id: args.item_id, stable_id: 'TASK-001', kind: 'task', archived: multiRun ? 0 : 1, title: `Item ${revision}` } };
      if (name === 'tapl_get_archive') return { archive: { id: args.archive_id, summary: `Archive ${revision}` }, items: [], events: [] };
      if (name === 'tapl_search_history') return { query: args.query, mode: 'bm25', results: [{ id: 1, title: `Search ${revision}` }] };
      throw new Error(`Unexpected tool: ${name}`);
    }
  }
  const originalLoad = Module._load;
  try {
    Module._load = function(name, ...args) {
      if (name === 'vscode') return vscode;
      if (name === './taplMcpClient') return { TaplMcpClientPool: Pool, taplMcpCommandCandidates: () => ['tapl-mcp'] };
      return originalLoad.call(this, name, ...args);
    };
    const mod = new Module(__filename, module); mod.filename = __filename; mod.paths = module.paths;
    mod._compile(refreshHostSource, __filename);
    mod.exports.activate({ extensionUri: 'extension', subscriptions: [] });
  } finally { Module._load = originalLoad; }
  const tick = () => new Promise(resolve => setImmediate(resolve));
  const until = async predicate => {
    const deadline = performance.now() + 1500;
    while (!predicate() && performance.now() < deadline) await new Promise(resolve => setTimeout(resolve, 1));
    assert.ok(predicate(), 'Expected asynchronous host response');
  };
  async function send(command) {
    const count = messages.length;
    await receive(command);
    for (let i = 0; i < 50 && messages.length === count; i++) await tick();
    assert.ok(messages.length > count, `No response for ${command.command}`);
    return messages.at(-1);
  }
  await commands.get('taplWorkflow.openOverview')();
  assert.equal(messages.at(-1).capabilities.associativeMemory, true);
  assert.match(panel.webview.html, /webview-dist\/assets\/index.js/);
  const list = await send({ command: 'memories', query: 'sqlite', offset: 50 });
  assert.equal(list.view.type, 'memories');
  assert.deepEqual(list.view.diagnostics, diagnostics);
  assert.deepEqual(calls.at(-1).args, { query: 'sqlite', offset: 50, limit: 50 });
  await send({ command: 'openMemory', memoryId: 'm1' });
  revision++;
  assert.equal((await send({ command: 'refresh' })).view.memory.note, 'Memory 2');
  assert.equal((await send({ command: 'openMemorySource', memoryId: 'm1' })).view.run.result_summary, 'Result 2');
  assert.equal((await send({ command: 'back' })).view.type, 'memory');
  itemSource = true;
  assert.equal((await send({ command: 'openMemorySource', memoryId: 'm1' })).view.detail.title, 'Item 2');
  assert.equal((await send({ command: 'back' })).view.type, 'memory');
  deleted = true;
  assert.equal((await send({ command: 'refresh' })).view.memory, null);
  const back = (await send({ command: 'back' })).view;
  assert.equal(back.query, 'sqlite');
  assert.equal(back.offset, 50);
  for (const [open, expected, field] of [
    [{ command: 'openArchive', archiveId: 'a1' }, 'archive', 'summary'],
    [{ command: 'search', query: 'sqlite' }, 'search', 'query'],
    [{ command: 'openSearchResult', itemId: 1 }, 'searchItem', 'title']
  ]) {
    await send(open); revision++;
    const refreshed = (await send({ command: 'refresh' })).view;
    assert.equal(refreshed.type, expected);
    if (expected === 'archive') assert.equal(refreshed.archive[field], `Archive ${revision}`);
    if (expected === 'search') assert.equal(refreshed.search.results[0].title, `Search ${revision}`);
    if (expected === 'searchItem') assert.equal(refreshed.detail[field], `Item ${revision}`);
  }
  const peerSource = 'tapl-peer.db';
  for (const open of [
    { command: 'openArchive', archiveId: 'a1' },
    { command: 'openSearchResult', itemId: 1 },
    { command: 'openMemory', memoryId: 'm1' }
  ]) {
    deleted = false;
    await send({ ...open, source_db: peerSource });
    assert.equal(calls.at(-1).args.source_db, peerSource, 'detail reads retain the selected database');
    await send({ command: 'refresh' });
    assert.equal(calls.at(-1).args.source_db, peerSource, 'refresh retains the selected database');
  }
  await send({ command: 'openMemorySource', memoryId: 'm1', source_db: peerSource });
  assert.equal(calls.at(-1).name, 'tapl_get_item');
  assert.equal(calls.at(-1).args.source_db, peerSource, 'memory original-source item keeps its database');
  diagnostics = undefined;
  assert.equal((await send({ command: 'memories' })).view.diagnostics, undefined, 'older memory hosts omit diagnostics safely');
  receive({ command: 'memories', query: 'slow' });
  while (!delayed) await tick();
  await send({ command: 'debug' });
  const count = messages.length;
  delayed(); await tick(); await tick();
  assert.equal(messages.length, count, 'stale data must not overwrite navigation');
  const callsBefore = calls.length;
  for (const command of ['updateMemory', 'deleteMemory', 'tapl_delete_memory']) receive({ command, memoryId: 'm1' });
  await tick(); assert.equal(calls.length, callsBefore);
  unavailable = true;
  await commands.get('taplWorkflow.openOverview')();
  assert.equal(messages.at(-1).view.type, 'error');
  unavailable = false;
  await send({ command: 'chooseWorkspace' }); await tick();
  assert.equal(messages.at(-1).workspace, '/work/second');
  assert.equal(watcherCount, 11);
  assert.ok(watchedPatterns.includes('.tapl/tapl-*.db'));
  assert.ok(watchedPatterns.includes('.tapl/tapl-*.db-wal'));
  assert.ok(!watchedPatterns.includes('.tapl/tapl-*.db-shm'), 'SHM lock traffic cannot trigger a refresh');
  folders.push(folder('third')); foldersChanged(); await tick();
  assert.equal(watcherCount, 16, 'watch newly added workspace folders and their config');
  folders.splice(1, 1); foldersChanged(); await until(() => messages.at(-1).workspace === '/work/first');
  assert.equal(messages.at(-1).workspace, '/work/first');
  assert.equal(panel.title, 'first tapl');
  multiRun = true;
  await commands.get('taplWorkflow.openOverview')();
  assert.equal(messages.at(-1).view.status.session_id, 'session-a');
  const foreignTask = (await send({ command: 'openSearchResult', itemId: 22 })).view.detail;
  assert.equal(foreignTask.active_execution, undefined, 'Run-local TASK-001 must not match another numeric item id');
  assert.equal(foreignTask.depends_on, undefined);
  await send({ command: 'selectRun', sessionId: 'session-b' });
  await tick();
  assert.equal(messages.at(-1).view.status.active_run.id, 'rb');
  assert.equal(messages.at(-1).view.status.plans[0].title, 'session-b');
  assert.ok(calls.some(call => call.name === 'tapl_get_status' && call.args.session_id === 'session-b'));
  assert.ok(calls.every(call => !['tapl_start_task', 'tapl_approve_execution', 'tapl_finish_archive'].includes(call.name)), 'Viewer selection must stay read-only');
  multiRun = false;
  oldServer = true;
  await commands.get('taplWorkflow.openOverview')();
  assert.equal(messages.at(-1).capabilities.associativeMemory, false);
  const beforeUnsupported = calls.length;
  receive({ command: 'memories' }); await tick();
  assert.equal(calls.length, beforeUnsupported);
  disposed();
});

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { buildSync } = require('esbuild');
const refreshHostSource = buildSync({ entryPoints: [path.join(__dirname, '../src/extension.ts')], bundle: true,
  write: false, platform: 'node', format: 'cjs', external: ['vscode', './taplMcpClient'] }).outputFiles[0].text;
const settle = () => new Promise(resolve => setTimeout(resolve, 25));

function refreshHost(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'tapl-host-refresh-'));
  const roots = ['first', 'second'].map(name => {
    const root = path.join(directory, name); fs.mkdirSync(path.join(root, '.tapl'), { recursive: true });
    fs.writeFileSync(path.join(root, '.tapl', 'tapl.db'), Buffer.alloc(4096));
    return { name, uri: { fsPath: root } };
  });
  const subscriptions = [], calls = [], messages = [], watchers = [], commands = new Map(), providers = [];
  const disposable = { dispose() {} }; let receive, viewState, focusState, release, slow = false;
  const state = { focused: true };
  const panel = { title: '', visible: true, active: true, reveal() { this.visible = true; },
    onDidChangeViewState(fn) { viewState = fn; return disposable; }, onDidDispose() { return disposable; },
    webview: { html: '', cspSource: 'test:', asWebviewUri(uri) { return uri; },
      onDidReceiveMessage(fn) { receive = fn; return disposable; },
      async postMessage(message) { messages.push(message); return true; } } };
  const vscode = {
    Uri: { joinPath(_base, ...parts) { return parts.join('/'); } }, TreeItem: class {}, ThemeIcon: class {},
    RelativePattern: class { constructor(root, pattern) { this.root = root.uri?.fsPath ?? root; this.pattern = pattern; } },
    EventEmitter: class { event() {} fire() {} }, TreeItemCollapsibleState: { None: 0 }, ViewColumn: { One: 1 },
    window: { state, onDidChangeWindowState(fn) { focusState = fn; return disposable; },
      registerTreeDataProvider(_name, provider) { providers.push(provider); return disposable; }, createWebviewPanel() { return panel; } },
    workspace: { workspaceFolders: roots, onDidChangeWorkspaceFolders() { return disposable; },
      createFileSystemWatcher(pattern) {
        const handlers = {}; watchers.push({ ...pattern, handlers });
        return { ...disposable, onDidChange(fn) { handlers.change = fn; return disposable; },
          onDidCreate(fn) { handlers.create = fn; return disposable; }, onDidDelete(fn) { handlers.delete = fn; return disposable; } };
      } },
    commands: { registerCommand(name, fn) { commands.set(name, fn); return disposable; },
      executeCommand(name) { return commands.get(name)?.(); } }, env: { language: 'en' }
  };
  class Pool {
    invalidate() {} async dispose() {}
    async callTool(workspace, name, args) {
      calls.push({ workspace: workspace.cwd, name, args });
      if (name === 'tapl_get_status') {
        // Reproduce SQLite's read-only sidecar churn without changing data.
        fs.writeFileSync(path.join(workspace.cwd, '.tapl', 'tapl.db-shm'), Buffer.alloc(32768));
        fs.writeFileSync(path.join(workspace.cwd, '.tapl', 'tapl.db-wal'), Buffer.alloc(32));
        if (slow) { slow = false; await new Promise(resolve => { release = resolve; }); }
        return { active_run: null, tasks: [], plans: [], findings: [], viewer_capabilities: {} };
      }
      if (name === 'tapl_list_archives') return { archives: [] };
      throw new Error(`Unexpected tool ${name}`);
    }
  }
  const load = Module._load; let extension;
  try {
    Module._load = function(name, ...args) {
      if (name === 'vscode') return vscode;
      if (name === './taplMcpClient') return { TaplMcpClientPool: Pool, taplMcpCommandCandidates: () => ['tapl-mcp'] };
      return load.call(this, name, ...args);
    };
    const mod = new Module(__filename, module); mod.filename = __filename; mod.paths = module.paths;
    // Keep production's trailing debounce semantics while avoiding seconds per case.
    mod._compile("const setTimeout = (fn, ms) => require('node:timers').setTimeout(fn, ms === 2000 ? 5 : ms);\n" + refreshHostSource, __filename);
    extension = mod.exports; extension.activate({ extensionUri: 'extension', subscriptions });
  } finally { Module._load = load; }
  t.after(async () => { subscriptions.forEach(value => value.dispose()); await extension.deactivate(); fs.rmSync(directory, { recursive: true, force: true }); });
  return { calls, messages, commands, providers, panel, state, roots,
    receive(message) { receive(message); },
    visible(value) { panel.visible = value; viewState({ webviewPanel: panel }); },
    focus(value) { state.focused = value; focusState(state); },
    slow() { slow = true; }, get release() { return release; },
    write(name = 'tapl.db', size = 8192, root = roots[0]) { fs.writeFileSync(path.join(root.uri.fsPath, '.tapl', name), Buffer.alloc(size)); },
    emit(pattern = '.tapl/tapl.db-wal', event = 'change', root = roots[0]) {
      const watcher = watchers.find(watcher => watcher.root === root.uri.fsPath && watcher.pattern === pattern);
      assert.ok(watcher, `Missing watcher ${pattern}`); watcher.handlers[event]();
    }
  };
}

test('read sidecar events stop at metadata checks; real data and explicit refresh rebuild once', async t => {
  const host = refreshHost(t);
  await host.commands.get('taplWorkflow.openOverview')();
  await host.commands.get('taplWorkflow.refresh')();
  const initial = host.calls.length;
  for (let i = 0; i < 3; i++) { host.emit(); await settle(); }
  assert.equal(host.calls.length, initial, 'status sidecars cannot cause the former repeating full refresh');
  host.write('tapl.db-wal', 0); host.emit(undefined, 'create'); await settle();
  assert.equal(host.calls.length, initial);
  host.write(); for (let i = 0; i < 50; i++) host.emit('.tapl/tapl.db'); await settle();
  assert.equal(host.calls.length, initial + 2, 'a database burst loads one overview snapshot');
  host.emit(); await settle(); assert.equal(host.calls.length, initial + 2);
  host.write('tapl-peer.db', 4096); host.emit('.tapl/tapl-*.db', 'create'); await settle();
  assert.equal(host.calls.length, initial + 4, 'new source databases invalidate the workspace');
  host.write('tapl.db', 8192, host.roots[1]); host.emit('.tapl/tapl.db', 'change', host.roots[1]); await settle();
  assert.equal(host.calls.length, initial + 4, 'other workspace events cannot refresh the selected workspace');
  host.receive({ command: 'refresh' }); await settle(); assert.equal(host.calls.length, initial + 6);
});

test('hidden and unfocused panels defer full snapshots and resume once', async t => {
  const host = refreshHost(t); await host.commands.get('taplWorkflow.openOverview')();
  const initial = host.calls.length; host.visible(false);
  host.write(); host.emit('.tapl/tapl.db'); await settle();
  host.write('tapl-peer.db'); host.emit('.tapl/tapl-*.db'); await settle();
  host.receive({ command: 'refresh' }); await settle();
  assert.equal(host.calls.length, initial, 'retained hidden panels do not build data');
  host.visible(true); host.visible(true); host.focus(true); await settle();
  assert.equal(host.calls.length, initial + 2, 'visibility and focus share one catch-up');
  host.focus(false); host.write('tapl.db', 12288); host.emit('.tapl/tapl.db'); await settle();
  assert.equal(host.calls.length, initial + 2);
  host.focus(true); host.focus(true); await settle(); assert.equal(host.calls.length, initial + 4);
  host.focus(true); await settle(); assert.equal(host.calls.length, initial + 4, 'unchanged focus only checks revisions');
});

test('a real commit during a delayed read is followed by one snapshot; refreshes never overlap', async t => {
  const host = refreshHost(t); await host.commands.get('taplWorkflow.openOverview')();
  const initial = host.calls.length; host.slow();
  const pending = host.commands.get('taplWorkflow.refresh')();
  while (!host.release) await new Promise(resolve => setImmediate(resolve));
  host.write(); for (let i = 0; i < 30; i++) host.emit('.tapl/tapl.db');
  assert.equal(host.calls.length, initial + 1, 'events do not start another full read while one is pending');
  host.release(); await pending; await settle();
  assert.equal(host.calls.length, initial + 4, 'the concurrent commit retains exactly one trailing snapshot');
  host.emit(); await settle(); assert.equal(host.calls.length, initial + 4);
});

test('hidden navigation invalidates an older in-flight snapshot before the catch-up', async t => {
  const host = refreshHost(t); await host.commands.get('taplWorkflow.openOverview')();
  host.slow(); const old = host.commands.get('taplWorkflow.openOverview')();
  while (!host.release) await new Promise(resolve => setImmediate(resolve));
  host.visible(false); host.receive({ command: 'debug' });
  host.visible(true); await settle();
  assert.equal(host.messages.at(-1).view.type, 'debug');
  const count = host.messages.length; host.release(); await old; await settle();
  assert.equal(host.messages.length, count, 'the old overview cannot overwrite hidden navigation');
});


test('tree reads cannot approve a retained hidden panel snapshot', async t => {
  const host = refreshHost(t); await host.commands.get('taplWorkflow.openOverview')();
  for (const provider of host.providers) {
    host.visible(false); host.write('tapl.db', 12288);
    await provider.getChildren();
    const callsAfterTree = host.calls.length, messagesBeforeResume = host.messages.length;
    host.emit('.tapl/tapl.db'); await settle();
    assert.equal(host.calls.length, callsAfterTree, 'hidden panel defers its snapshot');
    host.visible(true); await settle();
    assert.equal(host.calls.length, callsAfterTree + 2, 'tree baseline cannot swallow the pending panel update');
    assert.equal(host.messages.length, messagesBeforeResume + 1);
  }
});


test('one standalone tree read cannot consume another tree update', async t => {
  const host = refreshHost(t);
  await host.providers[0].getChildren();
  await host.commands.get('taplWorkflow.refresh')();
  host.write();
  await host.providers[1].getChildren();
  let invalidations = 0;
  const original = host.providers[0].refresh.bind(host.providers[0]);
  host.providers[0].refresh = () => { invalidations++; original(); };
  host.emit('.tapl/tapl.db'); await settle();
  assert.equal(invalidations, 1, 'the active tree still receives the real-change invalidation');
});

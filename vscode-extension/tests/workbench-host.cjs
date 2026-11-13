const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const tick = () => new Promise(resolve => setImmediate(resolve));

test('exact RUN and library host routes keep source/page/context without rebinding active selection', async () => {
  const calls = [], messages = [], commands = new Map();
  const disposable = { dispose() {} }, folders = [{ name: 'work', uri: { fsPath: '/work' } }];
  let receive, release, revision = 1, memoryItem = false, oldHost = false;
  const panel = { title: '', reveal() {}, onDidDispose() { return disposable; }, webview: {
    html: '', cspSource: 'local:', asWebviewUri(uri) { return uri; },
    onDidReceiveMessage(fn) { receive = fn; return disposable; },
    async postMessage(message) { messages.push(message); return true; }
  } };
  const vscode = {
    Uri: { joinPath(_base, ...parts) { return parts.join('/'); } },
    TreeItem: class {}, ThemeIcon: class {}, RelativePattern: class {}, EventEmitter: class { event() {} fire() {} },
    TreeItemCollapsibleState: { None: 0 }, ViewColumn: { One: 1 },
    window: { registerTreeDataProvider() { return disposable; }, createWebviewPanel() { return panel; } },
    workspace: { workspaceFolders: folders, getConfiguration() { return { get(_key, fallback) { return fallback; } }; },
      onDidChangeConfiguration() { return disposable; }, onDidChangeWorkspaceFolders() { return disposable; },
      createFileSystemWatcher() { return { ...disposable, onDidChange() { return disposable; }, onDidCreate() { return disposable; }, onDidDelete() { return disposable; } }; } },
    commands: { registerCommand(name, fn) { commands.set(name, fn); return disposable; }, async executeCommand(name) { return commands.get(name)?.(); } },
    env: { language: 'en' }
  };
  const snapshot = (runId, sourceDb) => ({ run: { id: runId, session_id: 'past-owner', status: 'archived', source_db: sourceDb, writable: false },
    readonly: true, plans: [], tasks: [], findings: [], task_counts: {}, active_batches: [], active_executions: [] });
  class Pool {
    invalidate() {}
    async dispose() {}
    async callTool(workspace, name, args) {
      calls.push({ root: workspace.cwd, name, args: { ...args } });
      if (name === 'tapl_get_status') return { active_run: { id: 'active', session_id: args.session_id ?? 'owner' },
        session_id: args.session_id ?? 'owner', active_runs: [{ id: 'active', session_id: 'owner' }], plans: [], tasks: [], findings: [],
        viewer_capabilities: { associativeMemory: true, discardRun: true } };
      if (name === 'tapl_list_archives') return { archives: [] };
      if (name === 'tapl_get_run') {
        if (oldHost) throw new Error('Unknown tool tapl_get_run');
        if (args.run_id === 'slow') await new Promise(resolve => { release = resolve; });
        return snapshot(args.run_id, args.source_db);
      }
      if (name === 'tapl_list_records') return { ...args, total: 65, records: [{ id: revision, run_id: 'past', source_db: args.source_db }],
        runs: [{ id: 'past', source_db: args.source_db, record_count: 65 }] };
      if (name === 'tapl_get_item') return { item: { id: args.item_id, run_id: 'past', source_db: args.source_db, kind: 'finding', stable_id: 'FIND-001', title: 'Original' } };
      if (name === 'tapl_get_archive') return { archive: { id: args.archive_id, run_id: 'past', source_db: args.source_db }, items: [], events: [] };
      if (name === 'tapl_get_memory') return { memory: { id: 'memory', source_db: args.source_db, source_available: true,
        source_record: memoryItem ? { kind: 'item', item: { id: 1 } } : { kind: 'run', run: { id: 'past' } } } };
      throw new Error(`Unexpected tool ${name}`);
    }
  }
  const original = Module._load;
  let extension;
  try {
    Module._load = function(name, ...args) {
      if (name === 'vscode') return vscode;
      if (name === './taplMcpClient') return { TaplMcpClientPool: Pool, taplMcpCommandCandidates: () => ['tapl-mcp'] };
      return original.call(this, name, ...args);
    };
    delete require.cache[require.resolve('../out/extension.js')];
    extension = require('../out/extension.js');
    extension.activate({ extensionUri: 'extension', subscriptions: [] });
  } finally { Module._load = original; }
  async function send(message) {
    const count = messages.length;
    await receive(message);
    for (let i = 0; i < 40 && messages.length === count; i++) await tick();
    assert.ok(messages.length > count, `No response to ${message.command}`);
    return messages.at(-1).view;
  }
  await commands.get('taplWorkflow.openOverview')();
  await send({ command: 'selectRun', sessionId: 'owner', source_db: 'tapl-local.db' });
  const exact = await send({ command: 'openRun', runId: 'past', source_db: 'tapl-peer.db' });
  assert.equal(exact.snapshot.run.id, 'past');
  assert.equal(exact.snapshot.readonly, true);
  assert.deepEqual(calls.at(-1).args, { run_id: 'past', source_db: 'tapl-peer.db' });
  await send({ command: 'refresh' });
  assert.deepEqual(calls.at(-1).args, { run_id: 'past', source_db: 'tapl-peer.db' });
  const page = await send({ command: 'records', scope: 'run', runId: 'past', source_db: 'tapl-peer.db', query: '50%_', offset: 50, limit: 15 });
  assert.equal(page.context.run.id, 'past');
  assert.equal(page.runs[0].record_count, 65);
  revision++;
  const refreshed = await send({ command: 'refresh' });
  assert.equal(refreshed.records[0].id, revision);
  assert.equal(refreshed.offset, 50);
  assert.deepEqual(calls.filter(call => call.name === 'tapl_list_records').at(-1).args,
    { query: '50%_', scope: 'run', offset: 50, limit: 15, run_id: 'past', source_db: 'tapl-peer.db' });
  await send({ command: 'openSearchResult', itemId: 1, source_db: 'tapl-peer.db' });
  assert.equal(messages.at(-1).view.context.run.id, 'past');
  assert.equal(messages.at(-1).view.result.run_id, 'past');
  assert.equal((await send({ command: 'back' })).offset, 50);
  for (const command of ['openArchive', 'openMemorySource']) {
    const source = await send({ command, archiveId: 'archive', memoryId: 'memory', source_db: 'tapl-peer.db' });
    assert.equal(source.context.run.id, 'past');
    assert.equal(source.context.run.source_db, 'tapl-peer.db');
  }
  memoryItem = true;
  assert.equal((await send({ command: 'openMemorySource', memoryId: 'memory', source_db: 'tapl-peer.db' })).context.run.id, 'past');
  oldHost = true;
  const compatible = await send({ command: 'openSearchResult', itemId: 1, source_db: 'tapl-peer.db' });
  assert.equal(compatible.type, 'searchItem');
  assert.equal(compatible.detail.title, 'Original');
  assert.equal(compatible.context, undefined, 'older hosts omit context without inventing a selected RUN');
  oldHost = false;
  await send({ command: 'records' });
  assert.deepEqual(calls.at(-1).args, { query: '', scope: 'all', offset: 0, limit: 50 });
  receive({ command: 'openRun', runId: 'slow', source_db: 'tapl-peer.db' });
  while (!release) await tick();
  const debug = await send({ command: 'debug' });
  assert.equal(debug.status.session_id, 'owner');
  assert.equal(calls.at(-1).args.source_db, 'tapl-local.db');
  const count = messages.length;
  release(); await tick(); await tick();
  assert.equal(messages.length, count, 'stale exact-run read cannot replace newer navigation');
  assert.match(panel.webview.html, /default-src 'none'/);
  await extension.deactivate();
});

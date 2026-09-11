const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');

test('extension uses the shared read-only Viewer protocol and reloads current routes', async () => {
  const calls = [], messages = [], commands = new Map();
  let receive, disposed, revision = 1, deleted = false, oldServer = false, delayed, foldersChanged, watcherCount = 0, unavailable = false, itemSource = false;
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
    TreeItem: class {}, ThemeIcon: class {}, RelativePattern: class {},
    EventEmitter: class { event() {} fire() {} }, TreeItemCollapsibleState: { None: 0 }, ViewColumn: { One: 1 },
    window: { registerTreeDataProvider() { return disposable; }, createWebviewPanel() { return panel; },
      async showWarningMessage() {}, async showWorkspaceFolderPick() { return folders[1]; } },
    workspace: { workspaceFolders: folders, getConfiguration() { return { get(_key, fallback) { return fallback; } }; },
      onDidChangeConfiguration() { return disposable; },
      onDidChangeWorkspaceFolders(fn) { foldersChanged = fn; return disposable; },
      createFileSystemWatcher() { watcherCount++; return { ...disposable, onDidChange() { return disposable; }, onDidCreate() { return disposable; }, onDidDelete() { return disposable; } }; } },
    commands: { registerCommand(name, fn) { commands.set(name, fn); return disposable; }, async executeCommand(name) { return commands.get(name)?.(); } },
    env: { language: 'en' }
  };
  class Pool {
    invalidate() {}
    async callTool(workspace, name, args) {
      calls.push({ root: workspace.cwd, name, args });
      if (name === 'tapl_get_status' && unavailable) throw new Error('No TAPL database');
      if (name === 'tapl_get_status') return { active_run: null, tasks: [], plans: [], findings: [],
        viewer_capabilities: oldServer ? undefined : { associativeMemory: true } };
      if (name === 'tapl_list_archives') return { archives: [] };
      if (name === 'tapl_recall') {
        if (args.query === 'slow') await new Promise(resolve => { delayed = resolve; });
        return { total: 51, memories: [memory()] };
      }
      if (name === 'tapl_get_memory') return { memory: deleted ? null : memory() };
      if (name === 'tapl_get_item') return { item: { id: args.item_id, stable_id: 'TASK-001', kind: 'task', archived: 1, title: `Item ${revision}` } };
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
    delete require.cache[require.resolve('../out/extension.js')];
    require('../out/extension.js').activate({ extensionUri: 'extension', subscriptions: [] });
  } finally { Module._load = originalLoad; }
  const tick = () => new Promise(resolve => setImmediate(resolve));
  async function send(command) {
    const count = messages.length;
    receive(command);
    for (let i = 0; i < 50 && messages.length === count; i++) await tick();
    assert.ok(messages.length > count, `No response for ${command.command}`);
    return messages.at(-1);
  }
  await commands.get('taplWorkflow.openOverview')();
  assert.equal(messages.at(-1).capabilities.associativeMemory, true);
  assert.match(panel.webview.html, /webview-dist\/assets\/index.js/);
  const list = await send({ command: 'memories', query: 'sqlite', offset: 50 });
  assert.equal(list.view.type, 'memories');
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
  assert.equal(watcherCount, 6);
  folders.push(folder('third')); foldersChanged(); await tick();
  assert.equal(watcherCount, 9, 'watch newly added workspace folders');
  folders.splice(1, 1); foldersChanged(); await tick();
  assert.equal(messages.at(-1).workspace, '/work/first');
  assert.equal(panel.title, 'first tapl');
  oldServer = true;
  await commands.get('taplWorkflow.openOverview')();
  assert.equal(messages.at(-1).capabilities.associativeMemory, false);
  const beforeUnsupported = calls.length;
  receive({ command: 'memories' }); await tick();
  assert.equal(calls.length, beforeUnsupported);
  disposed();
});

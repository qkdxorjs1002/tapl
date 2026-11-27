const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const tick = () => new Promise(resolve => setImmediate(resolve));

test('VSCode discard captures the target, rejects invalid commands, and preserves selection through async races', async () => {
  const calls = [], messages = [], commands = new Map();
  const disposable = { dispose() {} };
  const folders = ['first', 'second'].map(name => ({ name, uri: { fsPath: `/work/${name}` } }));
  let receive, delayed, fail = false, slow = false, supported = true;
  const source = 'tapl-local.db', claudeOwner = 'claude-code:b';
  let owners = ['a', 'b', 'c'];
  const ownerFor = key => key === 'b' ? claudeOwner : key;
  const panel = { title: '', reveal() {}, onDidDispose() { return disposable; }, webview: {
    html: '', cspSource: 'test:', asWebviewUri(uri) { return uri; },
    onDidReceiveMessage(fn) { receive = fn; return disposable; },
    async postMessage(message) { messages.push(message); return true; }
  } };
  const vscode = {
    Uri: { joinPath(_base, ...parts) { return parts.join('/'); } },
    TreeItem: class {}, ThemeIcon: class {}, RelativePattern: class {},
    EventEmitter: class { event() {} fire() {} }, TreeItemCollapsibleState: { None: 0 }, ViewColumn: { One: 1 },
    window: { registerTreeDataProvider() { return disposable; }, createWebviewPanel() { return panel; },
      async showWarningMessage() {}, async showWorkspaceFolderPick() { return folders[1]; } },
    workspace: { workspaceFolders: folders, getConfiguration() { return { get(_key, fallback) { return fallback; } }; },
      onDidChangeConfiguration() { return disposable; }, onDidChangeWorkspaceFolders() { return disposable; },
      createFileSystemWatcher() { return { ...disposable, onDidChange() { return disposable; },
        onDidCreate() { return disposable; }, onDidDelete() { return disposable; } }; } },
    commands: { registerCommand(name, fn) { commands.set(name, fn); return disposable; },
      async executeCommand(name) { return commands.get(name)?.(); } }, env: { language: 'en' }
  };
  class Pool {
    invalidate() {}
    async dispose() {}
    async supportsTool(_workspace, name) { return name === 'tapl_viewer_get_status' || (name === 'tapl_viewer_discard_run' && supported); }
    async callTool(workspace, name, args) {
      calls.push({ root: workspace.cwd, name, args: { ...args } });
      if (name === 'tapl_viewer_get_status') {
        const active_runs = owners.map(key => ({ id: `run-${key}`, session_id: ownerFor(key), source_db: source, writable: true, status: 'active' }));
        const active_run = (args.run_id ? active_runs.find(run => run.id === args.run_id && run.source_db === args.source_db) : active_runs[0]) ?? null;
        return { session_id: active_run?.session_id, active_run, active_runs, source_db: source, tasks: [], plans: [], findings: [],
          viewer_capabilities: { associativeMemory: true, discardRun: true } };
      }
      if (name === 'tapl_list_archives') return { archives: [] };
      if (name === 'tapl_viewer_discard_run') {
        if (slow) await new Promise(resolve => { delayed = resolve; });
        if (fail || args.source_db !== source || !owners.some(key => args.run_id === `run-${key}` && args.target_session_id === ownerFor(key))) throw new Error('stale_run');
        owners = owners.filter(key => `run-${key}` !== args.run_id);
        return { ok: true };
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
    delete require.cache[require.resolve('../out/extension.js')];
    extension = require('../out/extension.js');
    extension.activate({ extensionUri: 'extension', subscriptions: [] });
  } finally { Module._load = originalLoad; }
  const send = async message => { await receive(message); return messages.at(-1); };
  const discard = extra => ({ command: 'discardRun', runId: 'run-b', targetSessionId: claudeOwner, source_db: source,
    workspace: '/work/first', confirmed: true, confirmationRunId: 'run-b', ...extra });
  const select = key => send({ command: 'selectRun', runId: `run-${key}`, sessionId: ownerFor(key), source_db: source });
  const discardArgs = { source_db: source, run_id: 'run-b', target_session_id: claudeOwner, confirmed: true, confirmation_run_id: 'run-b' };
  await commands.get('taplWorkflow.openOverview')();
  assert.equal(messages.at(-1).capabilities.discardRun, true);
  assert.equal(messages.at(-1).view.status.session_id, 'a');
  await send({ command: 'selectRun', runId: 'run-b', source_db: source, sessionId: 'a' });
  assert.equal(messages.at(-1).view.status.session_id, claudeOwner, 'the selected RUN supplies the stored owner');
  await send({ command: 'refresh' });
  assert.deepEqual(calls.findLast(call => call.name === 'tapl_viewer_get_status').args,
    { full: true, include_events: false, events_limit: 12, run_id: 'run-b', source_db: source });
  await select('a');
  const before = calls.length;
  for (const extra of [{ confirmed: false }, { confirmed: 1 }, { confirmed: 'true' }, { confirmationRunId: undefined }, { confirmationRunId: '' },
    { confirmationRunId: 'run-' }, { confirmationRunId: 'RUN-B' }, { confirmationRunId: 'run-b ' },
    { confirmationRunId: ' run-b' }, { confirmationRunId: 1 }, { workspace: '/work/second' },
    { targetSessionId: undefined }, { targetSessionId: 'b\n' }, { source_db: undefined }, { source_db: '' }, { runId: '' }]) {
    assert.equal((await send(discard(extra))).discardResult.ok, false);
  }
  assert.equal(calls.length, before);
  await send(discard());
  assert.equal(messages.findLast(message => message.discardResult)?.discardResult.ok, true);
  assert.equal(messages.at(-1).view.status.session_id, 'a', 'closing B must retain selected A');
  assert.deepEqual(calls.find(call => call.name === 'tapl_viewer_discard_run').args, discardArgs);

  owners = ['a', 'b', 'c']; slow = true;
  const captured = discard(); const capturedResponse = receive(captured);
  while (!delayed) await tick();
  captured.workspace = '/work/second'; captured.targetSessionId = 'a'; captured.runId = 'run-a'; captured.confirmationRunId = 'run-a'; captured.source_db = 'tapl-peer.db';
  await select('c');
  delayed(); delayed = undefined;
  await capturedResponse;
  assert.equal(messages.at(-1).view.status.session_id, 'c', 'newer selected owner survives mutation response');
  assert.deepEqual(calls.filter(call => call.name === 'tapl_viewer_discard_run').at(-1).args, discardArgs);

  fail = true; const failedDiscard = receive(discard()); while (!delayed) await tick();
  await select('a');
  delayed(); delayed = undefined;
  await failedDiscard;
  assert.equal(messages.at(-1).type, 'error');
  assert.equal(messages.at(-1).discardResult.ok, false);
  assert.match(messages.at(-1).discardResult.message, /stale_run/);
  assert.equal(messages.findLast(message => message.view)?.view.status.session_id, 'a');

  fail = false; slow = false;
  await send(discard({ targetSessionId: 'a', runId: 'run-a', confirmationRunId: 'run-a' }));
  assert.equal(messages.at(-1).view.status.session_id, 'c', 'closing selected A reads remaining C');

  owners = ['a', 'b']; supported = false;
  await commands.get('taplWorkflow.openOverview')();
  assert.equal(messages.at(-1).capabilities.discardRun, false, 'status advertising discard is insufficient');
  const unsupportedBefore = calls.length;
  await send(discard());
  assert.equal(calls.length, unsupportedBefore);
  supported = true; await commands.get('taplWorkflow.openOverview')();
  slow = true; const workspaceDiscard = receive(discard()); while (!delayed) await tick();
  await send({ command: 'chooseWorkspace' });
  const workspaceCount = messages.length;
  delayed(); delayed = undefined;
  await workspaceDiscard;
  assert.equal(messages.length, workspaceCount, 'old workspace mutation cannot replace current board');
  assert.equal(messages.at(-1).workspace, '/work/second');
  assert.ok(calls.every(call => !('session_id' in call.args)));
  assert.ok(calls.every(call => !['tapl_get_status', 'tapl_discard_run'].includes(call.name)));
  await extension.deactivate();
});

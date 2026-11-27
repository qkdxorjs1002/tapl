const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const path = require('node:path');
const { buildSync } = require('esbuild');

const filename = path.join(__dirname, 'settings-client-render.cjs');
const output = buildSync({ entryPoints: [path.resolve(__dirname, '../src/taplMcpClient.ts')], bundle: true, platform: 'node', format: 'cjs', write: false, packages: 'external' }).outputFiles[0].text;
const compiled = new Module(filename, module);
compiled.filename = filename; compiled.paths = module.paths; compiled._compile(output, filename);
const { taplMcpEnvironment, WorkspaceTaplMcpClient } = compiled.exports;

test('lost settings-save acknowledgements never replay mutations; subsequent reads reconnect', async () => {
  const calls = []; let clients = 0;
  const factory = {
    createClient() {
      clients++;
      return { async connect() {}, async close() {}, async callTool({ name }) {
        calls.push(name);
        if (name === 'tapl_save_settings') throw new Error('Acknowledgement lost after save');
        return { structuredContent: { ok: true }, content: [] };
      } };
    },
    createTransport() { return {}; }
  };
  const client = new WorkspaceTaplMcpClient({ key: 'one', cwd: '/workspace', commands: ['tapl-mcp'] }, factory);
  try {
    await assert.rejects(client.callTool('tapl_save_settings', { values: { 'search.max_results': 20 }, expected_revision: 'old' }), /Acknowledgement lost/);
    assert.deepEqual(calls, ['tapl_save_settings']); assert.equal(clients, 1);
    assert.deepEqual(await client.callTool('tapl_get_settings'), { ok: true }); assert.equal(clients, 2);
  } finally { await client.dispose(); }
});

test('settings reads retain normal one-time recovery from a transport failure', async () => {
  let calls = 0;
  const client = new WorkspaceTaplMcpClient({ key: 'one', cwd: '/workspace', commands: ['tapl-mcp'] }, {
    createClient() { return { async connect() {}, async close() {}, async callTool() {
      if (++calls === 1) throw new Error('Read connection closed');
      return { structuredContent: { ok: true }, content: [] };
    } }; },
    createTransport() { return {}; }
  });
  try { assert.deepEqual(await client.callTool('tapl_get_settings'), { ok: true }); assert.equal(calls, 2); }
  finally { await client.dispose(); }
});

test('Viewer MCP advertises its mode and detects exact discard across paginated tool catalogs', async () => {
  const previousClient = process.env.TAPL_CLIENT, previousMode = process.env.TAPL_MCP_MODE;
  try {
    process.env.TAPL_CLIENT = 'claude-code';
    process.env.TAPL_MCP_MODE = 'agent';
    assert.equal(taplMcpEnvironment().TAPL_CLIENT, 'codex');
    assert.equal(taplMcpEnvironment().TAPL_MCP_MODE, 'viewer');
  } finally {
    for (const [key, value] of [['TAPL_CLIENT', previousClient], ['TAPL_MCP_MODE', previousMode]]) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }

  const pages = [], calls = [];
  let connections = 0;
  const client = new WorkspaceTaplMcpClient({ key: 'one', cwd: '/workspace', commands: ['tapl-mcp'] }, {
    createClient() {
      const connection = ++connections;
      return {
        async connect() {}, async close() {},
        async listTools({ cursor }) {
          pages.push([connection, cursor]);
          if (connection > 1) return { tools: [{ name: 'tapl_get_status' }, { name: 'tapl_discard_run' }] };
          return cursor
            ? { tools: [{ name: 'tapl_viewer_discard_run' }] }
            : { tools: [{ name: 'tapl_viewer_get_status' }], nextCursor: 'second-page' };
        },
        async callTool({ name, arguments: args }) {
          calls.push({ name, args });
          if (name === 'tapl_viewer_discard_run') throw new Error('Acknowledgement lost after discard');
          return { structuredContent: { ok: true }, content: [] };
        }
      };
    },
    createTransport() { return {}; }
  });
  const args = { source_db: 'tapl.db', run_id: 'run-b', target_session_id: 'claude-code:b', confirmed: true, confirmation_run_id: 'run-b' };
  try {
    assert.deepEqual(await Promise.all([client.supportsTool('tapl_viewer_get_status'), client.supportsTool('tapl_viewer_discard_run')]), [true, true]);
    await client.callTool('tapl_viewer_get_status', { run_id: 'run-b', source_db: 'tapl.db' });
    await assert.rejects(client.callTool('tapl_viewer_discard_run', args), /Acknowledgement lost after discard/);
    assert.equal(connections, 1, 'discard failure never reconnects to replay a mutation');
    assert.deepEqual(calls.at(-1), { name: 'tapl_viewer_discard_run', args });
    assert.equal(await client.supportsTool('tapl_viewer_discard_run'), false);
    await assert.rejects(client.callTool('tapl_viewer_discard_run', args), /does not support/);
    await client.callTool('tapl_get_status');
    assert.deepEqual(pages, [[1, undefined], [1, 'second-page'], [2, undefined]]);
    assert.deepEqual(calls.map(call => call.name), ['tapl_viewer_get_status', 'tapl_viewer_discard_run', 'tapl_get_status']);
  } finally { await client.dispose(); }
});

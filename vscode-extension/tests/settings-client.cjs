const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const path = require('node:path');
const { buildSync } = require('esbuild');

const filename = path.join(__dirname, 'settings-client-render.cjs');
const output = buildSync({ entryPoints: [path.resolve(__dirname, '../src/taplMcpClient.ts')], bundle: true, platform: 'node', format: 'cjs', write: false, packages: 'external' }).outputFiles[0].text;
const compiled = new Module(filename, module);
compiled.filename = filename; compiled.paths = module.paths; compiled._compile(output, filename);
const { WorkspaceTaplMcpClient } = compiled.exports;

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

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');

function load(source) {
  const filename = path.join(__dirname, `${source}-virtual.cjs`);
  const output = buildSync({ entryPoints: [path.join(__dirname, '../src', `${source}.ts`)], bundle: true,
    platform: 'node', format: 'cjs', write: false, external: ['@modelcontextprotocol/sdk/*'] }).outputFiles[0].text;
  const mod = new Module(filename, module); mod.filename = filename; mod.paths = module.paths; mod._compile(output, filename);
  return mod.exports;
}
const { loadViewerConfig, viewerConfigRequiresTrust } = load('viewerConfig');
const defaults = { language: 'auto', layout: 'auto', mcp_path: '' };
test('user-scoped relative executables still require workspace trust', () => {
  const configuration = (scope, mcp_path) => ({ scope, path: '/config.toml', exists: true, preferences: { ...defaults, mcp_path } });
  assert.equal(viewerConfigRequiresTrust(configuration('workspace', '/trusted/program')), true);
  for (const command of ['./tapl-mcp', '../bin/tapl-mcp', 'custom-program']) {
    assert.equal(viewerConfigRequiresTrust(configuration('user', command)), true);
  }
  assert.equal(viewerConfigRequiresTrust(configuration('user', path.resolve('/trusted/program'))), false);
  assert.equal(viewerConfigRequiresTrust(configuration('workspace', '')), false);
});
function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'tapl-viewer-config-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const workspace = path.join(root, 'parent', 'workspace'), homeDir = path.join(root, 'home');
  fs.mkdirSync(workspace, { recursive: true }); fs.mkdirSync(homeDir, { recursive: true });
  const local = path.join(workspace, '.tapl', 'config.toml'), user = path.join(homeDir, '.tapl', 'config.toml');
  const write = (file, text) => { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, text); };
  return { workspace, homeDir, local, user, write, read: () => loadViewerConfig(workspace, { homeDir }) };
}

test('bootstrap selects one local or user file, never ancestors or per-key merges', t => {
  const h = fixture(t);
  h.write(path.join(path.dirname(h.workspace), '.tapl', 'config.toml'), '[viewer]\nlanguage="ko"');
  assert.deepEqual(h.read(), { path: h.local, exists: false, scope: 'workspace', preferences: defaults });
  h.write(h.user, '[viewer]\nlanguage="ko"\nlayout="large"\nmcp_path="custom-server"');
  assert.deepEqual(h.read().preferences, { language: 'ko', layout: 'large', mcp_path: 'custom-server' });
  assert.equal(h.read().scope, 'user');
  h.write(h.local, '[viewer]\nlayout="small"');
  assert.deepEqual(h.read().preferences, { ...defaults, layout: 'small' });
  assert.equal(h.read().path, h.local);
  fs.unlinkSync(h.local); assert.equal(h.read().path, h.user);
  fs.unlinkSync(h.user); assert.deepEqual(h.read().preferences, defaults);
});

test('native TOML bootstrap handles dotted/quoted keys, multiline strings and unrelated values', t => {
  const h = fixture(t);
  h.write(h.local, `viewer.language = " KO "\nviewer.layout = 'Medium'\nviewer.mcp_path = '''/a directory/tapl-mcp'''\n[unrelated]\ntext = """literal [viewer] # ignored\nlayout = 'invalid'"""\nlarge_integer = 9223372036854775807\ndates = [1979-05-27T07:32:00Z]\n`);
  assert.deepEqual(h.read().preferences, { language: 'ko', layout: 'medium', mcp_path: '/a directory/tapl-mcp' });
  h.write(h.local, '"viewer" = { "language" = "en", "layout" = "large" }');
  assert.deepEqual(h.read().preferences, { ...defaults, language: 'en', layout: 'large' });
});

test('invalid selected TOML and bootstrap fields fail clearly without user fallback', t => {
  const h = fixture(t); h.write(h.user, '[viewer]\nlanguage="en"');
  for (const text of ['[viewer', '[viewer]\nlanguage="ko"\nlanguage="en"', 'viewer="ko"', 'viewer=[]',
    '[viewer]\nlanguage=true', '[viewer]\nlanguage="fr"', '[viewer]\nlayout="tiny"',
    '[viewer]\nmcp_path=[]', '[viewer]\nmcp_path="bad\\npath"', '[viewer]\nmcp_path="bad\\u0085path"']) {
    h.write(h.local, text);
    assert.throws(h.read, error => error.message.includes(h.local) && /Unable to read TAPL configuration/.test(error.message));
  }
  fs.writeFileSync(h.local, Buffer.from([0x23, 0x20, 0xc0, 0xaf]));
  assert.throws(h.read, /Unable to read TAPL configuration/);
  fs.writeFileSync(h.local, '\ufeff[viewer]\nlanguage="en"');
  assert.throws(h.read, /Unable to read TAPL configuration/);
});

test('bootstrap observes external edits, creation, deletion and exact executable strings', t => {
  const h = fixture(t); assert.equal(h.read().exists, false);
  h.write(h.local, '[viewer]\nlanguage="en"\nmcp_path="  /a directory/tapl-mcp  "');
  assert.equal(h.read().preferences.mcp_path, '  /a directory/tapl-mcp  ');
  h.write(h.local, '[viewer]\nlanguage="ko"\nlayout="large"');
  assert.deepEqual(h.read().preferences, { ...defaults, language: 'ko', layout: 'large' });
  fs.unlinkSync(h.local); assert.equal(h.read().exists, false);
});

test('configured MCP command is the sole unchanged executable; only empty discovers defaults', () => {
  const { taplMcpCommandCandidates } = load('taplMcpClient');
  for (const value of ['/a directory/tapl-mcp', 'tapl-mcp --flag', ' ', '  tapl-mcp  ']) {
    assert.deepEqual(taplMcpCommandCandidates(value), [value]);
  }
  assert.deepEqual(taplMcpCommandCandidates('', 'linux'), ['tapl-mcp', '/opt/homebrew/bin/tapl-mcp', '/usr/local/bin/tapl-mcp']);
  assert.deepEqual(taplMcpCommandCandidates('', 'win32'), ['tapl-mcp.exe']);
});

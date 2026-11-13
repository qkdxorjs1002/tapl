const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const Module = require('node:module');
const { buildSync } = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const output = buildSync({
  stdin: { contents: `export * from './src/webview/workbench/mindmap';
    export * from './src/webview/workbench/runReferences';
    export * from './src/webview/workbench/mindmapCache';
    export * from './src/webview/workbench/mindmapRelations';
    export { mindmapConnectionGeometry } from './src/webview/workbench/mindmapGeometry';
    export { snapshotForView } from './src/webview/workbench/model';
    export { CurrentRun } from './src/webview/workbench/RunViews';
    export { I18nProvider } from './src/webview/i18n';`, resolveDir: path.resolve(__dirname, '..') },
  bundle: true, platform: 'node', format: 'cjs', write: false, jsx: 'automatic', loader: { '.css': 'empty' }, external: ['react', 'react-dom']
}).outputFiles[0].text;
const compiled = new Module(path.join(__dirname, 'run-references-render.cjs'), module);
compiled.filename = path.join(__dirname, 'run-references-render.cjs');
compiled.paths = module.paths;
compiled._compile(output, compiled.filename);
const { buildRunMindmap, runReferenceKey, runReferenceCommand, runMindmapReferences, latestRunReference,
  memoryReferencesHistory, runMindmapProjection, sameMindmapValue, snapshotForView,
  buildMindmapRelationIndex, relatedMindmapNodes, CurrentRun, I18nProvider } = compiled.exports;
const run = { id: 'current', source_db: '/workspace/current.sqlite3', status: 'active', request_summary: 'Current work' };
const snapshot = (references = []) => ({ run, plans: [{ id: 1, kind: 'plan', stable_id: 'PLAN-001', title: 'Plan', status: 'Finalized' }],
  tasks: [{ id: 2, kind: 'task', stable_id: 'TASK-001', spec_id: 'PLAN-001', title: 'Task', status: 'Completed' }],
  findings: [], task_counts: { Completed: 1 }, active_batches: [], active_executions: [], readonly: false, references });
const history = (extra = {}) => ({ kind: 'history', stage: 'retrieved', target_type: 'item', source_db: '/peer/a.sqlite3',
  run_id: 'past', item_id: 7, stable_id: 'TASK-007', record_kind: 'task', title: 'Original task', ...extra });
const memory = (extra = {}) => ({ kind: 'memory', stage: 'retrieved', target_type: 'memory', source_db: '/peer/memory.sqlite3',
  run_id: 'past', memory_id: 'M-007', title: 'Remember the constraint',
  source: { source_db: '/peer/a.sqlite3', run_id: 'past', item_id: 7 }, ...extra });
const nodeFor = (graph, reference) => graph.nodes.find(node => node.key === runReferenceKey(reference));
const referenceEdges = graph => graph.edges.filter(edge => edge.relation);

test('RUN reference branches connect through upper and lower boundaries in both directions', () => {
  const m = memory({ stage: 'opened' });
  const graph = buildRunMindmap(snapshot([m]));
  assert.equal(graph.routing, 'radial');
  const root = graph.nodes[0], target = nodeFor(graph, m);
  const connect = compiled.exports.mindmapConnectionGeometry;
  const forward = connect(root, target, graph.routing);
  assert.equal(forward.start.y, root.y + root.height / 2);
  assert.equal(forward.end.y, target.y - target.height / 2);
  assert.ok(forward.control1.y > forward.start.y);
  assert.ok(forward.control2.y < forward.end.y);
  const reverse = connect(target, root, graph.routing);
  assert.deepEqual(reverse.start, forward.end);
  assert.deepEqual(reverse.end, forward.start);
});

test('retrieval nodes have no invented links; opening only the original creates a provenance path', () => {
  const m = memory(), h = history(), unrelated = history({ item_id: 8, stable_id: 'PLAN-008', record_kind: 'plan' });
  const retrieved = buildRunMindmap(snapshot([m, h, unrelated]));
  assert.equal(referenceEdges(retrieved).length, 0);
  assert.equal(retrieved.nodes.filter(node => node.reference).length, 3);
  const opened = { ...h, stage: 'opened' };
  const graph = buildRunMindmap(snapshot([m, opened, unrelated]));
  assert.deepEqual(referenceEdges(graph).map(({from, to, relation, flowing}) => ({from, to, relation, flowing})), [
    { from: runReferenceKey(m), to: runReferenceKey(h), relation: 'memory-source', flowing: false },
    { from: graph.nodes[0].key, to: runReferenceKey(m), relation: 'memory', flowing: false }
  ]);
  assert.ok(!graph.edges.some(edge => edge.to === runReferenceKey(unrelated)));
  const related = relatedMindmapNodes(buildMindmapRelationIndex(graph), nodeFor(graph, h).key);
  assert.ok(related.has(nodeFor(graph, m).key));
  assert.ok(related.has(graph.nodes[0].key));
  assert.ok(!related.has(nodeFor(graph, unrelated).key));
});

test('source, RUN and exact item provenance prevent false cross-source or parent links', () => {
  const opened = history({ stage: 'opened' });
  for (const change of [
    { source_db: '/peer/b.sqlite3', run_id: 'past', item_id: 7 },
    { source_db: '/peer/a.sqlite3', run_id: 'other-run', item_id: 7 },
    { source_db: '/peer/a.sqlite3', run_id: 'past', item_id: 8 },
    { source_db: '/peer/a.sqlite3', run_id: 'past', item_id: null }
  ]) {
    const m = memory({ source: change });
    assert.equal(memoryReferencesHistory(m, opened), false);
    const graph = buildRunMindmap(snapshot([m, opened]));
    assert.deepEqual(referenceEdges(graph).map(edge => edge.relation), ['history']);
  }
  const runHistory = history({ target_type: 'run', item_id: undefined, stage: 'opened' });
  assert.equal(memoryReferencesHistory(memory(), runHistory), false, 'an item pointer never broadens to its RUN');
  assert.equal(memoryReferencesHistory(memory({source: { source_db: runHistory.source_db, run_id: 'past', archive_id: 'archive-1' }}), runHistory), true);
  const graph = buildRunMindmap(snapshot([opened, { ...opened, source_db: '/peer/b.sqlite3' }]));
  assert.equal(graph.nodes.filter(node => node.reference).length, 2);
  assert.equal(new Set(graph.nodes.map(node => node.key)).size, graph.nodes.length);
});

test('opened promotion deduplicates reads, guards current RUN records and preserves workflow totals', () => {
  const h = history(), opened = { ...h, stage: 'opened' }, m = memory({ stage: 'opened' });
  const value = snapshot([h, opened, h, m,
    history({ source_db: run.source_db, run_id: run.id, item_id: 2 }),
    history({ source_db: run.source_db, run_id: run.id, target_type: 'run' })]);
  assert.deepEqual(runMindmapReferences(value).map(ref => ref.stage), ['opened', 'opened']);
  const baseline = buildRunMindmap(snapshot()), graph = buildRunMindmap(value);
  assert.deepEqual([graph.completed, graph.total, graph.percent], [1, 1, 100]);
  assert.deepEqual(graph.nodes.filter(node => !node.reference), baseline.nodes);
  assert.deepEqual(graph.edges.filter(edge => !edge.relation), baseline.edges);
  assert.equal(graph.nodes.filter(node => node.reference).length, 2);
  for (const node of graph.nodes.filter(node => node.reference)) {
    assert.equal(node.completed, 0); assert.equal(node.total, 0);
    assert.ok(node.y - node.height / 2 > Math.max(...baseline.nodes.map(node => node.y + node.height / 2)));
  }
  assert.ok(referenceEdges(graph).every(edge => !edge.flowing));
});

test('a source RUN open creates one root target and never manufactures historical children', () => {
  const ref = history({ target_type: 'run', item_id: undefined, stage: 'opened' });
  const graph = buildRunMindmap(snapshot([ref]));
  assert.equal(graph.nodes.filter(node => node.reference).length, 1);
  assert.equal(graph.nodes.filter(node => node.kind === 'plan').length, 1);
  assert.equal(graph.nodes.filter(node => node.kind === 'task').length, 1);
  assert.deepEqual(referenceEdges(graph), [{ from: graph.nodes[0].key, to: runReferenceKey(ref), flowing: false, relation: 'history' }]);
});

test('status projection carries references and invalidates card, stage and provenance changes', () => {
  const original = snapshot([memory(), history()]);
  const status = { active_run: run, ...original }; delete status.run;
  assert.equal(snapshotForView({type: 'overview', status}).references, original.references);
  const projection = runMindmapProjection(original);
  for (const change of [
    value => { value.references[1].stage = 'opened'; },
    value => { value.references[0].title = 'A new title'; },
    value => { value.references[0].source.item_id = 99; },
    value => { value.references[0].source.source_db = '/other/source'; },
    value => { value.references[1].source_db = '/other/source'; },
    value => { value.references[1].stable_id = 'PLAN-123'; },
    value => { value.references.pop(); }
  ]) {
    const changed = structuredClone(original); change(changed);
    assert.equal(sameMindmapValue(projection, runMindmapProjection(changed)), false);
  }
  // Ordering does not reflow the graph. Unknown host metadata is outside the UI projection.
  const reordered = structuredClone(original); reordered.references.reverse();
  assert.equal(sameMindmapValue(projection, runMindmapProjection(reordered)), true);
});

test('navigation resolves fresh records and always supplies the exact database for all target types', () => {
  const old = history(), latest = { ...old, stage: 'opened', title: 'Latest original' }, value = snapshot([latest]);
  assert.equal(latestRunReference(value, old), latest);
  assert.equal(latestRunReference(snapshot([]), old), undefined);
  assert.deepEqual(runReferenceCommand(latest), { command: 'openSearchResult', itemId: 7, source_db: '/peer/a.sqlite3' });
  assert.deepEqual(runReferenceCommand(memory()), { command: 'openMemory', memoryId: 'M-007', source_db: '/peer/memory.sqlite3' });
  assert.deepEqual(runReferenceCommand(history({ target_type: 'run' })), { command: 'openRun', runId: 'past', source_db: '/peer/a.sqlite3' });
  assert.equal(runReferenceCommand(history({ item_id: NaN })), undefined);
});

test('a retained RUN card invokes the latest committed reference handler without rebuilding the graph', () => {
  const source = buildSync({ entryPoints: [path.join(__dirname, '../src/webview/workbench/RunMindmap.tsx')],
    bundle: true, platform: 'node', format: 'cjs', write: false, jsx: 'automatic', loader: {'.css': 'empty'},
    external: ['react', 'react/jsx-runtime', '../i18n', './mindmapViewport', './MindmapEdges', './Icon'] }).outputFiles[0].text;
  let cursor = 0, effects = [], graph;
  const slots = [];
  const memo = (compute, deps) => {
    const index = cursor++, previous = slots[index];
    if (!previous || !deps || deps.some((dep, i) => !Object.is(dep, previous.deps[i]))) slots[index] = {value: compute(), deps};
    return slots[index].value;
  };
  const effect = (callback, deps) => memo(() => { effects.push(callback); }, deps);
  const react = {...React, memo: value => value,
    useRef: value => { const index = cursor++; return slots[index] ??= {current: value}; },
    useState: value => { const index = cursor++; return [slots[index] ??= value, () => {}]; },
    useMemo: memo, useCallback: (callback, deps) => memo(() => callback, deps), useEffect: effect, useLayoutEffect: effect};
  const component = {exports: {}};
  new Function('module', 'exports', 'require', source)(component, component.exports, name => {
    if (name === 'react') return react;
    if (name === '../i18n') return {useI18n: () => ({t: key => key, status: value => value})};
    if (name === './mindmapViewport') return {useMindmapViewport: value => {
      graph = value.graph; return {hostRef: {}, worldRef: {}, controlsRef: {}, edges: [], following: false};
    }};
    if (name === './MindmapEdges') return {MindmapEdge: () => null};
    if (name === './Icon') return {Icon: () => null};
    return require(name);
  });
  const render = (value, handler) => {
    cursor = 0; effects = [];
    const tree = component.exports.RunMindmap({snapshot: value, open() {}, openReference: handler});
    effects.forEach(effect => effect());
    const world = React.Children.toArray(tree.props.children).find(child => child.props?.className === 'wb-mm-world');
    return React.Children.toArray(world.props.children).find(child => child.props?.node?.reference);
  };
  const old = memory(), value = snapshot([old]);
  const card = render(value, () => assert.fail('stale callback'));
  const firstGraph = graph, next = structuredClone(value), opened = [];
  next.references[0].source.archive_id = 'fresh-source-metadata';
  render(next, reference => opened.push(reference));
  assert.equal(graph, firstGraph, 'non-rendered metadata leaves layout and interactions intact');
  card.props.openReference(card.props.node.reference);
  assert.equal(opened[0], next.references[0]);
  render(snapshot([]), () => assert.fail('removed reference must never open'));
  card.props.openReference(card.props.node.reference);
});

test('reference stages, kind legend and jump controls render in both languages without completion badges', () => {
  const value = snapshot([memory(), history({stage: 'opened', title: '<script>Escaped original</script>'})]);
  for (const [locale, labels] of [['en', ['Retrieved', 'Opened', 'Show memory references', 'Show history references']],
    ['ko', ['조회', '원문 확인', '기억 참조 보기', '과거 기록 참조 보기']]]) {
    const html = renderToStaticMarkup(React.createElement(I18nProvider, {locale}, React.createElement(CurrentRun,
      {snapshot: value, open() {}, openReference() {}})));
    labels.forEach(label => assert.ok(html.includes(label), label));
    assert.match(html, /data-kind="memory" data-reference-stage="retrieved"/);
    assert.match(html, /data-kind="history" data-reference-stage="opened"/);
    assert.match(html, /&lt;script&gt;Escaped original&lt;\/script&gt;/);
    assert.equal((html.match(/wb-mm-run-numbers/g) ?? []).length, 1);
    assert.equal((html.match(/wb-mm-plan-track/g) ?? []).length, 1);
    assert.equal((html.match(/wb-mm-reference-jump/g) ?? []).length, 2);
    assert.doesNotMatch(html, /<script>/);
  }
});

test('palette adapters retain theme tokens for native and explicit browser themes', () => {
  const styles = fs.readFileSync(path.join(__dirname, '../src/webview/styles.css'), 'utf8');
  const themes = fs.readFileSync(path.join(__dirname, '../src/webview/workbench/workbench.css'), 'utf8');
  const map = fs.readFileSync(path.join(__dirname, '../src/webview/workbench/run-mindmap.css'), 'utf8');
  assert.match(styles, /--tapl-reference-memory: var\(--vscode-charts-purple,/);
  assert.match(styles, /--tapl-reference-history: var\(--vscode-charts-orange,/);
  for (const name of ['memory', 'history']) {
    assert.equal((themes.match(new RegExp(`--tapl-reference-${name}:`, 'g')) ?? []).length, 2);
    assert.match(map, new RegExp(`--mm-${name}: var\\(--tapl-reference-${name}\\)`));
  }
});

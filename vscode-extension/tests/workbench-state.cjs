const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { buildSync } = require('esbuild');

const output = buildSync({
  entryPoints: [path.join(__dirname, '../src/webview/workbench/model.ts')],
  bundle: true, platform: 'node', format: 'cjs', write: false
}).outputFiles[0].text;
const compiled = { exports: {} };
new Function('module', 'exports', output)(compiled, compiled.exports);
const model = compiled.exports;
const run = { id: 'same-id', source_db: 'main.sqlite3', session_id: 'owner', request_summary: 'Local work', status: 'active' };
const peer = { ...run, source_db: 'peer.sqlite3', request_summary: 'Peer work', writable: false };
const snapshot = (selected = run) => ({ run: selected, plans: [], tasks: [], findings: [], task_counts: {}, active_batches: [], active_executions: [], readonly: selected.writable === false, active_runs: [run] });
const runView = (selected = run) => ({ type: 'run', snapshot: snapshot(selected) });
const recordsView = (selected = run) => ({ type: 'records', query: '', scope: 'all', offset: 0, limit: 50, total: 0, records: [], runs: [run, peer], context: snapshot(selected) });
const itemView = (selected = peer, id = 81) => ({ type: 'searchItem', result: { id, stable_id: 'TASK-001', kind: 'task', title: 'A source record', search_source: 'history', source_db: selected.source_db }, detail: { id, stable_id: 'TASK-001', kind: 'task', title: 'A source record', run_id: selected.id, source_db: selected.source_db }, context: snapshot(selected) });

test('RUN and record groups preserve arbitrary same IDs across sources', () => {
  assert.notEqual(model.runKey(run), model.runKey(peer));
  assert.equal(model.recordRunKey(peer.source_db, peer.id), model.runKey(peer));
  assert.notEqual(model.runKey({ source_db: 'a|b', id: 'c' }), model.runKey({ source_db: 'a', id: 'b|c' }));
  assert.equal(model.uniqueRuns([run, peer, { ...run, request_summary: 'Updated' }]).length, 2);
});

test('tabs append exactly one selected archive and drop it on active navigation', () => {
  const archived = { ...peer, status: 'archived' };
  assert.deepEqual(model.tabRuns([run, archived], archived), [run, archived]);
  assert.deepEqual(model.tabRuns([run, archived], run), [run]);
  assert.deepEqual(model.tabRuns([run], peer), [run, peer]);
});

test('polling the current RUN does not reset TASK selection, filter or query', () => {
  let state = model.createNavigation(runView());
  state = model.navigate(state, { page: 'tasks', runKey: model.runKey(run) }, false);
  state = model.patchPage(state, { taskFilter: 'Skipped', taskQuery: 'saved value', sidebarScroll: 155 });
  const refreshed = model.receiveView(state, { ...runView(), snapshot: { ...snapshot(), task_counts: { Completed: 4 } } });
  assert.equal(refreshed.route.page, 'tasks');
  assert.equal(model.pageState(refreshed).taskFilter, 'Skipped');
  assert.equal(model.pageState(refreshed).taskQuery, 'saved value');
  assert.equal(model.pageState(refreshed).sidebarScroll, 155);
});

test('internal cross-source detail keeps Back, filters, groups, tracks and focus', () => {
  const library = recordsView();
  let state = model.createNavigation(library);
  const origin = state.route;
  state = model.patchPage(state, { group: 'run', expanded: [model.runKey(peer)], query: 'evidence', positions: {
    [model.routeIdentity(origin)]: { top: 820, tracks: { flow: 440, plans: 200 }, focus: 'record:peer:81' }
  } });
  state = model.navigate(state, { page: 'legacy', runKey: model.runKey(peer) }, true, model.viewIdentity(itemView()));
  state = model.receiveView(state, itemView());
  assert.equal(state.route.runKey, model.runKey(peer));
  assert.equal(state.trail.length, 1);
  state = model.back(state, model.viewIdentity(library));
  assert.equal(state.route, origin);
  const restored = model.pageState(state);
  assert.equal(restored.query, 'evidence');
  assert.deepEqual(restored.expanded, [model.runKey(peer)]);
  assert.deepEqual(restored.positions[model.routeIdentity(origin)], { top: 820, tracks: { flow: 440, plans: 200 }, focus: 'record:peer:81' });
});

test('stale polling cannot replace an explicit pending detail or consume Back', () => {
  let state = model.createNavigation(recordsView());
  state = model.navigate(state, { page: 'legacy', runKey: model.runKey(peer) }, true, model.viewIdentity(itemView()));
  assert.equal(model.receiveView(state, runView()), state);
  assert.equal(model.receiveView(state, itemView(run)), state);
  const loaded = model.receiveView(state, itemView());
  assert.equal(loaded.pending, undefined);
  assert.equal(loaded.trail.length, 1);
  assert.equal(loaded.route.view.detail.id, 81);
});

test('memory ITEM source accepts the actual detailed-record response with matching provenance', () => {
  let state = model.createNavigation(runView());
  const expected = JSON.stringify(['memorySource', peer.source_db, 'memory-1']);
  state = model.navigate(state, { page: 'legacy', runKey: model.runKey(run) }, true, expected);
  assert.equal(model.receiveView(state, itemView(run)), state);
  const loaded = model.receiveView(state, itemView(peer));
  assert.equal(loaded.pending, undefined);
  assert.equal(loaded.route.page, 'legacy');
  assert.equal(loaded.route.runKey, model.runKey(peer));
  assert.equal(loaded.trail.length, 1);
});

test('memory RUN source opens the source RUN page and selects its composite key', () => {
  let state = model.createNavigation(runView());
  const source = { type: 'memorySource', source_db: peer.source_db, memoryId: 'memory-2', run: peer, context: snapshot(peer) };
  state = model.navigate(state, { page: 'legacy', runKey: model.runKey(run) }, true, model.viewIdentity(source));
  state = model.receiveView(state, source);
  assert.equal(state.route.page, 'current');
  assert.equal(state.route.runKey, model.runKey(peer));
  assert.equal(state.route.view, undefined);
  assert.equal(state.trail.length, 1);
});

test('records start all-scope and collapsed; manual groups survive polling and preferences', () => {
  let state = model.createNavigation(recordsView());
  assert.equal(model.pageState(state).scope, 'all');
  assert.deepEqual(model.pageState(state).expanded, []);
  state = model.patchPage(state, { expanded: [model.runKey(peer)], group: 'record' });
  state = model.receiveView(state, { ...recordsView(), total: 99 });
  assert.deepEqual(model.pageState(state).expanded, [model.runKey(peer)]);
  state = model.patchPage(state, { group: 'run' });
  assert.deepEqual(model.pageState(state).expanded, [model.runKey(peer)]);
  state = model.receiveView(state, { ...recordsView(), query: 'new query' });
  assert.deepEqual(model.pageState(state).expanded, []);
});

test('page updates and pagination retain the existing internal trail without adding entries', () => {
  let state = model.createNavigation(runView());
  state = model.navigate(state, { page: 'records', runKey: model.runKey(run), view: recordsView() }, true);
  const next = { ...recordsView(), offset: 50, total: 100 };
  state = model.navigate(state, { page: 'records', runKey: model.runKey(run), view: next }, 'replace', model.viewIdentity(next));
  assert.equal(state.trail.length, 1);
  assert.equal(state.trail[0].page, 'current');
  state = model.navigate(state, { page: 'tasks', runKey: model.runKey(run) }, false);
  assert.equal(state.trail.length, 0);
});

test('reload restores per-RUN preferences but never a historical Back trail or stale view', () => {
  let state = model.createNavigation(runView());
  state = model.patchPage(state, { taskFilter: 'Blocked', taskQuery: 'local', group: 'record', expanded: ['saved-group'] });
  state = model.navigate(state, { page: 'legacy', runKey: model.runKey(peer) }, true);
  state = model.patchPage(state, { taskQuery: 'peer' });
  const restored = model.createNavigation(runView(), model.persistedNavigation(state));
  assert.equal(restored.trail.length, 0);
  assert.equal(restored.route.page, 'current');
  assert.equal(model.pageState(restored).taskQuery, 'local');
  assert.equal(model.pageState(restored, model.runKey(peer)).taskQuery, 'peer');
  assert.deepEqual(model.pageState(restored).expanded, ['saved-group']);
});

test('task completion uses actual server totals and retains skipped/custom status filtering', () => {
  const data = { ...snapshot(), task_counts: { Completed: 2, Skipped: 1, 'In Progress': 2, Waiting: 1 }, tasks: [{ id: 1, stable_id: 'TASK-001', kind: 'task', title: 'Local task', status: 'Completed' }] };
  assert.deepEqual(model.taskCounts(data), { total: 6, completed: 2, percent: 33, counts: data.task_counts });
  const tasks = [...data.tasks, { id: 2, stable_id: 'TASK-002', kind: 'task', title: 'Skipped task', status: 'Skipped' }];
  assert.deepEqual(model.filterTasks(tasks, 'Skipped', 'task-002').map((item) => item.id), [2]);
});

test('failed internal requests retain the preceding page for Back', () => {
  let state = model.createNavigation(recordsView());
  state = model.navigate(state, { page: 'legacy', runKey: model.runKey(peer) }, true, model.viewIdentity(itemView()));
  state = model.receiveView(state, { type: 'error', message: 'Source unavailable' });
  assert.equal(state.pending, undefined);
  assert.equal(state.route.view.message, 'Source unavailable');
  assert.equal(state.trail.length, 1);
});

test('an ended selected RUN clears its context while leaving other active tabs selectable', () => {
  let state = model.createNavigation(runView());
  const empty = { type: 'overview', archives: [], searchQuery: '', status: { active_run: null, active_runs: [peer], plans: [], tasks: [], findings: [], task_counts: {}, incomplete_tasks: 0, recent_events: [], schema: {} } };
  state = model.receiveView(state, empty);
  assert.equal(state.route.runKey, '');
  assert.equal(state.route.page, 'current');
  assert.deepEqual(model.runsForView(empty), [peer]);
});

test('a RUN snapshot can precede restoration of its cached records page', () => {
  const library = recordsView(peer);
  let state = model.createNavigation(runView());
  state = model.navigate(state, { page: 'records', runKey: model.runKey(peer), view: library }, false, model.viewIdentity(runView(peer)));
  state = model.receiveView(state, runView(peer));
  assert.equal(state.route.page, 'records');
  assert.equal(state.route.view, library);
  assert.equal(state.route.runKey, model.runKey(peer));
  assert.equal(state.trail.length, 0);
});

test('archive contexts use the same RUN page while archive events remain detailed', () => {
  const archive = { id: peer.id, slug: 'history', summary: 'Saved records', created_at: '2026-11-10', source_db: peer.source_db };
  assert.equal(model.routeForView({ type: 'archive', archive, context: snapshot(peer) }).page, 'current');
  assert.equal(model.routeForView({ type: 'archiveEvents', archive, context: snapshot(peer) }).page, 'legacy');
  assert.equal(model.routeForView({ type: 'archive', archive }).page, 'legacy');
});

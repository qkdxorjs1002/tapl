const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { buildSync } = require('esbuild');
const React = require('react');

// Exercise the real component's hook boundary; only DOM viewport and presentation context are stubbed.
const source = buildSync({
  entryPoints: [path.join(__dirname, '../src/webview/workbench/RunMindmap.tsx')],
  bundle: true, platform: 'node', format: 'cjs', write: false, jsx: 'automatic', loader: { '.css': 'empty' },
  external: ['react', 'react/jsx-runtime', '../i18n', './mindmapViewport', './MindmapEdges', './Icon']
}).outputFiles[0].text;

function harness() {
  let cursor = 0, effects = [], graph;
  const slots = [];
  const memo = (compute, deps) => {
    const index = cursor++, previous = slots[index];
    if (!previous || !deps || deps.some((dep, i) => !Object.is(dep, previous.deps[i]))) slots[index] = { value: compute(), deps };
    return slots[index].value;
  };
  const effect = (callback, deps) => memo(() => { effects.push(callback); }, deps);
  const react = { ...React, memo: value => value,
    useRef: value => { const index = cursor++; return slots[index] ??= { current: value }; },
    useState: value => { const index = cursor++; if (!slots[index]) slots[index] = { value: typeof value === 'function' ? value() : value }; return [slots[index].value, next => { slots[index].value = next; }]; },
    useMemo: memo, useCallback: (callback, deps) => memo(() => callback, deps), useEffect: effect, useLayoutEffect: effect
  };
  const compiled = { exports: {} };
  new Function('module', 'exports', 'require', source)(compiled, compiled.exports, name => {
    if (name === 'react') return react;
    if (name === '../i18n') return { useI18n: () => ({ t: key => key, status: value => value }) };
    if (name === './mindmapViewport') return { useMindmapViewport: value => {
      graph = value.graph; return { hostRef: {}, worldRef: {}, controlsRef: {}, edges: [], following: false };
    } };
    if (name === './MindmapEdges') return { MindmapEdge: () => null };
    if (name === './Icon') return { Icon: () => null };
    return require(name);
  });
  return { render(snapshot, open) {
    cursor = 0; effects = [];
    const tree = compiled.exports.RunMindmap({ snapshot, open });
    effects.forEach(effect => effect());
    const children = React.Children.toArray(tree.props.children);
    const cards = React.Children.toArray(children.find(child => child.props?.className === 'wb-mm-world').props.children)
      .filter(child => child.props?.node);
    return { graph, cards };
  } };
}

test('actual RUN component retains graph identity through live timing and opens latest committed body', () => {
  const render = harness();
  const snapshot = { run: { id: 'r', source_db: 'local', status: 'active' }, plans: [], tasks: [
    { id: 1, stable_id: 'TASK-1', kind: 'task', title: 'Task', status: 'Completed', body: 'old', execution_timing: { elapsed_seconds: 10, as_of: 'first' } }
  ] };
  const opened = [];
  const first = render.render(snapshot, (item, run) => opened.push({ item, run }));
  const oldCard = first.cards.find(card => card.props.node.kind === 'task');
  const next = structuredClone(snapshot);
  next.tasks[0].execution_timing.as_of = 'second'; next.tasks[0].body = 'new body';
  next.run.result_summary = 'new run detail';
  const second = render.render(next, (item, run) => opened.push({ item, run }));
  assert.equal(second.graph, first.graph, 'timing-only and body-only refresh never reruns layout');
  assert.equal(second.cards.find(card => card.props.node.kind === 'task').props.node, oldCard.props.node);
  oldCard.props.open(oldCard.props.node.item);
  assert.equal(opened[0].item, next.tasks[0]); assert.equal(opened[0].item.body, 'new body');
  assert.equal(opened[0].run, next.run);
  for (const modify of [
    value => { value.tasks[0].title = 'New title'; },
    value => { value.tasks[0].status = 'In Progress'; },
    value => { value.tasks[0].spec_id = 'PLAN-2'; },
    value => { value.run.source_db = 'peer'; }
  ]) {
    const changed = structuredClone(next); modify(changed);
    assert.notEqual(render.render(changed, () => {}).graph, first.graph);
  }
});

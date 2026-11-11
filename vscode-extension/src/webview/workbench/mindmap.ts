import type { TaplItem, TaplRunSnapshot } from '../types';

export interface MindmapNode {
  key: string;
  kind: 'run' | 'plan' | 'task';
  /** Coordinates are node centers, in the RUN's coordinate system. */
  x: number;
  y: number;
  width: number;
  height: number;
  parent?: string;
  item?: TaplItem;
  title: string;
  status?: string;
  completed: number;
  total: number;
}

export interface MindmapGraph {
  nodes: MindmapNode[];
  edges: { from: string; to: string; flowing: boolean }[];
  bounds: { minX: number; minY: number; maxX: number; maxY: number };
  completed: number;
  total: number;
  percent: number;
}

interface Branch {
  node: MindmapNode;
  children: MindmapNode[];
  height: number;
  order: number;
}

const TASK_STEP = 88;
const GROUP_GAP = 48;
const collator = new Intl.Collator('en', { numeric: true, sensitivity: 'variant' });

function compareText(a: string, b: string): number {
  // Numeric collation treats e.g. TASK-1 and TASK-01 equally; break that tie explicitly.
  return collator.compare(a, b) || (a < b ? -1 : a > b ? 1 : 0);
}

function compareItems(a: TaplItem, b: TaplItem): number {
  // Stable IDs give polling snapshots the same layout even when their SQL order changes.
  return (
    compareText(a.stable_id, b.stable_id) ||
    (a.id ?? 0) - (b.id ?? 0) ||
    compareText(a.kind, b.kind) ||
    compareText(a.title, b.title) ||
    compareText(a.status ?? '', b.status ?? '')
  );
}

/** Build a source-safe, deterministic tree without mutating the snapshot or its records. */
export function buildRunMindmap(snapshot: TaplRunSnapshot): MindmapGraph {
  const source = snapshot.run.source_db ?? '';
  const run = snapshot.run.id ?? '';
  const belongsToRun = (item: TaplItem): boolean =>
    (item.source_db === undefined || item.source_db === source) && (item.run_id === undefined || item.run_id === run);
  const plans = snapshot.plans.filter(belongsToRun).sort(compareItems);
  const tasks = snapshot.tasks.filter(belongsToRun).sort(compareItems);
  const completed = tasks.filter((task) => task.status === 'Completed').length;
  const total = tasks.length;
  const root: MindmapNode = {
    key: JSON.stringify(['run', source, run]),
    kind: 'run',
    x: 0,
    y: 0,
    width: 238,
    height: 158,
    title: snapshot.run.request_summary ?? '',
    status: snapshot.run.status,
    completed,
    total
  };
  const usedKeys = new Map<string, number>();
  const makeNode = (item: TaplItem, kind: 'plan' | 'task'): MindmapNode => {
    const identity = [item.source_db ?? source, item.run_id ?? run, kind, item.kind, item.id ?? null, item.stable_id];
    const identityKey = JSON.stringify(identity);
    const occurrence = usedKeys.get(identityKey) ?? 0;
    usedKeys.set(identityKey, occurrence + 1);
    return {
      key: JSON.stringify(['item', ...identity, occurrence]),
      kind,
      x: 0,
      y: 0,
      width: kind === 'plan' ? 216 : 210,
      height: kind === 'plan' ? 100 : 66,
      parent: root.key,
      item,
      title: item.title,
      status: item.status,
      completed: kind === 'task' && item.status === 'Completed' ? 1 : 0,
      total: kind === 'task' ? 1 : 0
    };
  };
  const branches: Branch[] = plans.map((item, order) => ({
    node: makeNode(item, 'plan'),
    children: [],
    height: 100,
    order
  }));
  // An ambiguous duplicate PLAN stable ID is not a safe parent either.
  const plansById = new Map<string, Branch | null>();
  for (const branch of branches) {
    const id = branch.node.item!.stable_id;
    if (id) plansById.set(id, plansById.has(id) ? null : branch);
  }
  for (const item of tasks) {
    const node = makeNode(item, 'task');
    const parent = item.spec_id ? plansById.get(item.spec_id) : undefined;
    if (parent) {
      node.parent = parent.node.key;
      parent.children.push(node);
      parent.node.total += 1;
      parent.node.completed += node.completed;
    } else {
      branches.push({ node, children: [], height: node.height, order: branches.length });
    }
  }
  for (const branch of branches) {
    branch.height = Math.max(branch.node.height, (branch.children.length - 1) * TASK_STEP + 66);
  }

  // Place the largest subtrees first to balance both sides; retain natural record order
  // within each side. Height includes all children, so adjacent groups never overlap.
  const lanes: Branch[][] = [[], []];
  const heights = [0, 0];
  for (const branch of [...branches].sort((a, b) => b.height - a.height || a.order - b.order)) {
    const lane = heights[0] <= heights[1] ? 0 : 1;
    lanes[lane].push(branch);
    heights[lane] += branch.height + (lanes[lane].length > 1 ? GROUP_GAP : 0);
  }
  for (let side = 0; side < lanes.length; side += 1) {
    let top = -heights[side] / 2;
    const direction = side === 0 ? -1 : 1;
    for (const branch of lanes[side].sort((a, b) => a.order - b.order)) {
      branch.node.x = direction * 310;
      branch.node.y = top + branch.height / 2;
      const firstChildY = branch.node.y - ((branch.children.length - 1) * TASK_STEP) / 2;
      branch.children.forEach((node, index) => {
        node.x = direction * 610;
        node.y = firstChildY + index * TASK_STEP;
      });
      top += branch.height + GROUP_GAP;
    }
  }

  const nodes = [root, ...branches.flatMap((branch) => [branch.node, ...branch.children])];
  const byKey = new Map(nodes.map((node) => [node.key, node]));
  const executing = new Set<string>();
  if (snapshot.run.status === 'active') {
    for (const node of nodes) {
      if (node.kind === 'run' || node.status !== 'In Progress') continue;
      // Mark the incoming edge and its ancestors, without lighting idle sibling branches.
      let current: MindmapNode | undefined = node;
      while (current?.parent && !executing.has(current.key)) {
        executing.add(current.key);
        current = byKey.get(current.parent);
      }
    }
  }
  const bounds = { minX: -119, minY: -79, maxX: 119, maxY: 79 };
  for (const node of nodes) {
    bounds.minX = Math.min(bounds.minX, node.x - node.width / 2);
    bounds.minY = Math.min(bounds.minY, node.y - node.height / 2);
    bounds.maxX = Math.max(bounds.maxX, node.x + node.width / 2);
    bounds.maxY = Math.max(bounds.maxY, node.y + node.height / 2);
  }
  return {
    nodes,
    edges: nodes.filter((node) => node.parent).map((node) => ({ from: node.parent!, to: node.key, flowing: executing.has(node.key) })),
    bounds,
    completed,
    total,
    percent: total ? Math.round((completed / total) * 100) : 0
  };
}

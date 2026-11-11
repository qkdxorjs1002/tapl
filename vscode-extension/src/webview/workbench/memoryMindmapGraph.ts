import type { AssociativeMemory } from '../types';

export interface MemoryMindmapNode {
  key: string;
  kind: 'source' | 'memory' | 'cue';
  x: number;
  y: number;
  width: number;
  height: number;
  title: string;
  memory?: AssociativeMemory;
  cue?: string;
  count: number;
  matched?: boolean;
}

export interface MemoryMindmapGraph {
  nodes: MemoryMindmapNode[];
  edges: { from: string; to: string; relation: 'source' | 'cue' }[];
  bounds: { minX: number; minY: number; maxX: number; maxY: number };
  memoryCount: number;
  sourceCount: number;
  cueCount: number;
}

// This is deliberately JavaScript lowercase, not Python's broader casefold.
function cueIdentity(value: string): string {
  return value.normalize('NFKC').toLowerCase().replace(/\s+/gu, ' ').trim();
}

function key(kind: MemoryMindmapNode['kind'], ...parts: unknown[]): string {
  return JSON.stringify([kind, ...parts]);
}

function sourceIdentity(memory: AssociativeMemory, memoryKey: string): string | undefined {
  const source = memory.source;
  if (!source || typeof source !== 'object') return undefined;
  const hasRun = typeof source.run_id === 'string' && source.run_id.trim().length > 0;
  const hasItem = typeof source.item_id === 'number' && Number.isFinite(source.item_id);
  // Empty provenance cannot establish a relationship, even if a title exists.
  if (!hasRun && !hasItem) return undefined;
  const complete =
    typeof memory.source_db === 'string' &&
    memory.source_db.trim().length > 0 &&
    hasRun &&
    ((source.kind === 'item' && hasItem) || (source.kind === 'run' && source.item_id === null));
  return complete
    ? key('source', memory.source_db, source.run_id, source.kind, source.item_id)
    : key('source', 'incomplete', memoryKey);
}

/** Build only provenance and cue relationships present on the current results page. */
export function buildMemoryMindmap(memories: AssociativeMemory[]): MemoryMindmapGraph {
  const graph: MemoryMindmapGraph = {
    nodes: [],
    edges: [],
    bounds: { minX: 0, minY: 0, maxX: 0, maxY: 0 },
    memoryCount: 0,
    sourceCount: 0,
    cueCount: 0
  };
  const memoryNodes = new Map<string, MemoryMindmapNode>();
  const sources = new Map<string, MemoryMindmapNode>();
  const cues = new Map<string, { node: MemoryMindmapNode; memories: MemoryMindmapNode[] }>();
  // Map insertion order preserves the first result's rank within each source group.
  const groups = new Map<string, { source?: MemoryMindmapNode; memories: MemoryMindmapNode[] }>();

  for (const memory of memories) {
    if (memory.state === 'deleted') continue;
    const memoryKey = key('memory', memory.source_db ?? null, memory.id);
    if (memoryNodes.has(memoryKey)) continue;
    const node: MemoryMindmapNode = {
      key: memoryKey,
      kind: 'memory',
      x: 470,
      y: 0,
      width: 300,
      height: 132,
      title: memory.note,
      memory,
      count: 1
    };
    memoryNodes.set(memoryKey, node);
    const sourceKey = sourceIdentity(memory, memoryKey);
    let sourceNode: MemoryMindmapNode | undefined;
    if (sourceKey) {
      sourceNode = sources.get(sourceKey);
      if (!sourceNode) {
        sourceNode = {
          key: sourceKey,
          kind: 'source',
          x: 110,
          y: 0,
          width: 220,
          height: 90,
          title: memory.source.title || memory.source.run_id || memory.id,
          memory,
          count: 0
        };
        sources.set(sourceKey, sourceNode);
      } else if (!sourceNode.memory?.source_available && memory.source_available) {
        sourceNode.memory = memory;
        sourceNode.title = memory.source.title || memory.source.run_id || memory.id;
      }
      sourceNode.count += 1;
      graph.edges.push({ from: sourceKey, to: memoryKey, relation: 'source' });
    }
    const groupKey = sourceKey ?? memoryKey;
    let group = groups.get(groupKey);
    if (!group) {
      group = { source: sourceNode, memories: [] };
      groups.set(groupKey, group);
    }
    group.memories.push(node);

    const seenCues = new Set<string>();
    for (const cue of Array.isArray(memory.cue) ? memory.cue : []) {
      if (typeof cue !== 'string') continue;
      const identity = cueIdentity(cue);
      if (!identity || seenCues.has(identity)) continue;
      seenCues.add(identity);
      const cueKey = key('cue', identity);
      let entry = cues.get(cueKey);
      if (!entry) {
        entry = {
          node: { key: cueKey, kind: 'cue', x: 820, y: 0, width: 200, height: 54, title: cue, cue, count: 0 },
          memories: []
        };
        cues.set(cueKey, entry);
      }
      entry.node.count += 1;
      entry.node.matched ||= (memory.matched_cues ?? []).some((matched) => cueIdentity(matched) === identity);
      entry.memories.push(node);
      graph.edges.push({ from: memoryKey, to: cueKey, relation: 'cue' });
    }
  }

  graph.memoryCount = memoryNodes.size;
  graph.sourceCount = sources.size;
  graph.cueCount = cues.size;
  if (!graph.memoryCount) return graph;

  // Give dense cue columns room without ever reducing the memory card gap.
  const step = Math.max(164, (cues.size * 78) / memoryNodes.size);
  let nextY = 0;
  for (const group of groups.values()) {
    const firstY = nextY;
    for (const node of group.memories) {
      node.y = nextY;
      nextY += step;
    }
    if (group.source) {
      const last = group.memories[group.memories.length - 1];
      group.source.y = (firstY + last.y) / 2;
    }
    nextY += 40;
  }

  const orderedCues = [...cues.values()]
    .map((entry, index) => ({
      ...entry,
      index,
      target: entry.memories.reduce((sum, node) => sum + node.y, 0) / entry.memories.length
    }))
    .sort((a, b) => a.target - b.target || a.index - b.index);
  let previousBottom = -Infinity;
  let displacement = 0;
  for (const entry of orderedCues) {
    entry.node.y = Math.max(entry.target, previousBottom + 24 + entry.node.height / 2);
    displacement += entry.node.y - entry.target;
    previousBottom = entry.node.y + entry.node.height / 2;
  }
  // Center the collision-free packing around its desired barycenters.
  const cueShift = orderedCues.length ? displacement / orderedCues.length : 0;
  for (const entry of orderedCues) entry.node.y -= cueShift;

  graph.nodes = [...sources.values(), ...memoryNodes.values(), ...Array.from(cues.values(), (entry) => entry.node)];
  let minX = Infinity,
    minY = Infinity,
    maxX = -Infinity,
    maxY = -Infinity;
  for (const node of graph.nodes) {
    minX = Math.min(minX, node.x - node.width / 2);
    minY = Math.min(minY, node.y - node.height / 2);
    maxX = Math.max(maxX, node.x + node.width / 2);
    maxY = Math.max(maxY, node.y + node.height / 2);
  }
  const centerX = (minX + maxX) / 2,
    centerY = (minY + maxY) / 2;
  for (const node of graph.nodes) {
    node.x -= centerX;
    node.y -= centerY;
  }
  graph.bounds = { minX: minX - centerX, minY: minY - centerY, maxX: maxX - centerX, maxY: maxY - centerY };
  return graph;
}

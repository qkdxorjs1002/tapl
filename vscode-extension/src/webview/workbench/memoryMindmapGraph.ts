import type { AssociativeMemory } from '../types';

export interface MemoryMindmapNode {
  key: string;
  kind: 'workspace' | 'source' | 'memory' | 'cue';
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
  edges: { from: string; to: string; relation: 'workspace' | 'source' | 'cue' }[];
  bounds: { minX: number; minY: number; maxX: number; maxY: number };
  memoryCount: number;
  sourceCount: number;
  cueCount: number;
  routing?: 'radial';
}

export interface MemoryMindmapOptions {
  workspaceKey?: string;
  workspaceTitle?: string;
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

const NODE_GAP = 24;
const RADIAL_STEP = 88;
const ANGULAR_STEP = 76;

/** A spatial index keeps collision checks local even for hundreds of shared cues. */
class NodePlacement {
  private readonly cells = new Map<string, MemoryMindmapNode[]>();
  private readonly cellSize = 256;

  private visit(node: MemoryMindmapNode, padding: number, callback: (cell: string) => boolean): boolean {
    const firstX = Math.floor((node.x - node.width / 2 - padding) / this.cellSize);
    const lastX = Math.floor((node.x + node.width / 2 + padding) / this.cellSize);
    const firstY = Math.floor((node.y - node.height / 2 - padding) / this.cellSize);
    const lastY = Math.floor((node.y + node.height / 2 + padding) / this.cellSize);
    for (let x = firstX; x <= lastX; x += 1) {
      for (let y = firstY; y <= lastY; y += 1) {
        if (!callback(`${x},${y}`)) return false;
      }
    }
    return true;
  }

  add(node: MemoryMindmapNode): void {
    this.visit(node, NODE_GAP, (cell) => {
      const nodes = this.cells.get(cell);
      if (nodes) nodes.push(node);
      else this.cells.set(cell, [node]);
      return true;
    });
  }

  private fits(node: MemoryMindmapNode): boolean {
    return this.visit(node, 0, (cell) => {
      for (const other of this.cells.get(cell) ?? []) {
        if (
          Math.abs(node.x - other.x) < (node.width + other.width) / 2 + NODE_GAP &&
          Math.abs(node.y - other.y) < (node.height + other.height) / 2 + NODE_GAP
        )
          return false;
      }
      return true;
    });
  }

  /** Search expanding radial rows, preferring the parent direction in each sector. */
  place(node: MemoryMindmapNode, angle: number, radius: number, halfSector: number, preferred = angle): void {
    const preferredOffset = Math.max(-halfSector, Math.min(halfSector, angleDelta(preferred, angle)));
    for (let row = 0; ; row += 1) {
      const distance = radius + row * RADIAL_STEP;
      const angleStep = ANGULAR_STEP / distance;
      const steps = Math.ceil((halfSector + Math.abs(preferredOffset)) / angleStep);
      for (let step = 0; step <= steps; step += 1) {
        const offsets =
          step === 0 ? [preferredOffset] : [preferredOffset + step * angleStep, preferredOffset - step * angleStep];
        for (const offset of offsets) {
          if (Math.abs(offset) > halfSector + 1e-9) continue;
          const direction = angle + offset;
          node.x = Math.cos(direction) * distance;
          node.y = Math.sin(direction) * distance;
          if (Math.abs(node.x) < 1e-9) node.x = 0;
          if (Math.abs(node.y) < 1e-9) node.y = 0;
          if (this.fits(node)) {
            this.add(node);
            return;
          }
        }
      }
    }
  }
}

function angleDelta(angle: number, center: number): number {
  return Math.atan2(Math.sin(angle - center), Math.cos(angle - center));
}

/**
 * The workspace is a result-collection anchor, including connected databases.
 * Only the source and cue edges describe relationships in the returned memories.
 */
export function buildMemoryMindmap(
  memories: AssociativeMemory[],
  options: MemoryMindmapOptions = {}
): MemoryMindmapGraph {
  const graph: MemoryMindmapGraph = {
    nodes: [],
    edges: [],
    bounds: { minX: 0, minY: 0, maxX: 0, maxY: 0 },
    memoryCount: 0,
    sourceCount: 0,
    cueCount: 0,
    routing: 'radial'
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
      x: 0,
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
          x: 0,
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
          node: { key: cueKey, kind: 'cue', x: 0, y: 0, width: 200, height: 54, title: cue, cue, count: 0 },
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

  const workspace: MemoryMindmapNode = {
    key: key('workspace', options.workspaceKey ?? null),
    kind: 'workspace',
    x: 0,
    y: 0,
    width: 240,
    height: 96,
    title: options.workspaceTitle ?? 'Workspace',
    count: graph.memoryCount
  };
  const placement = new NodePlacement();
  placement.add(workspace);
  const sectors = [...groups.values()].map((group, index) => ({
    ...group,
    angle: (index * Math.PI * 2) / groups.size,
    // One branch still fans outward; two branches use opposite half-planes.
    halfSector: Math.min(Math.PI / 2, Math.PI / groups.size) * 0.92
  }));
  const memorySectors = new Map<string, (typeof sectors)[number]>();

  // Keep source anchors close to the workspace regardless of descendant count.
  // Extra sources use outward slots along their own ray when labels would clash.
  for (const sector of sectors) {
    if (sector.source) placement.place(sector.source, sector.angle, 340, 0);
    graph.edges.push({ from: workspace.key, to: sector.source?.key ?? sector.memories[0].key, relation: 'workspace' });
  }
  for (const sector of sectors) {
    const radius = sector.source ? Math.hypot(sector.source.x, sector.source.y) + 350 : 360;
    for (const node of sector.memories) {
      placement.place(node, sector.angle, radius, sector.halfSector);
      memorySectors.set(node.key, sector);
    }
  }
  for (const entry of cues.values()) {
    const parentSectors = new Set(entry.memories.map((node) => memorySectors.get(node.key)!));
    const firstSector = memorySectors.get(entry.memories[0].key)!;
    const sumX = entry.memories.reduce((sum, node) => sum + node.x, 0);
    const sumY = entry.memories.reduce((sum, node) => sum + node.y, 0);
    const preferred = Math.hypot(sumX, sumY) > 1e-8 ? Math.atan2(sumY, sumX) : firstSector.angle;
    const radius = Math.max(...entry.memories.map((node) => Math.hypot(node.x, node.y))) + 320;
    // A cue shared across sectors is still one node with every true parent.
    // Its placement may use the full circle; it does not invent an owning source.
    placement.place(
      entry.node,
      parentSectors.size === 1 ? firstSector.angle : preferred,
      radius,
      parentSectors.size === 1 ? firstSector.halfSector : Math.PI,
      preferred
    );
  }

  graph.nodes = [
    workspace,
    ...sources.values(),
    ...memoryNodes.values(),
    ...Array.from(cues.values(), (entry) => entry.node)
  ];
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
  graph.bounds = { minX, minY, maxX, maxY };
  return graph;
}

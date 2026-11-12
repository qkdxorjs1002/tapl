type RelationGraph = {
  nodes: readonly { key: string; parent?: string }[];
  edges: readonly { from: string; to: string }[];
};

export type MindmapRelationIndex = {
  keys: ReadonlySet<string>;
  children: ReadonlyMap<string, readonly string[]>;
  parents: ReadonlyMap<string, readonly string[]>;
};

/** Build once per graph, rather than scanning every edge at each visited node. */
export function buildMindmapRelationIndex(
  graph: RelationGraph,
  ancestorSource: 'edges' | 'node-parent' = 'edges'
): MindmapRelationIndex {
  const keys = new Set<string>();
  const children = new Map<string, string[]>();
  const parents = new Map<string, string[]>();
  const add = (index: Map<string, string[]>, key: string, next: string) => {
    const adjacent = index.get(key);
    if (adjacent) adjacent.push(next);
    else index.set(key, [next]);
  };
  for (const node of graph.nodes) {
    keys.add(node.key);
    // RUN ancestry follows the recorded parent field, including a dangling parent.
    if (ancestorSource === 'node-parent' && node.parent) add(parents, node.key, node.parent);
  }
  for (const edge of graph.edges) {
    add(children, edge.from, edge.to);
    if (ancestorSource === 'edges') add(parents, edge.to, edge.from);
  }
  return { keys, children, parents };
}

/** Trace ancestors and descendants separately: shared parents must not pull in siblings. */
export function relatedMindmapNodes(
  index: MindmapRelationIndex,
  active?: string | readonly string[],
  { ancestorsOnly = false }: { ancestorsOnly?: boolean } = {}
): Set<string> | undefined {
  const seeds = (typeof active === 'string' ? [active] : active ?? []).filter(key => index.keys.has(key));
  if (!seeds.length) return undefined;
  const related = new Set(seeds);
  for (const direction of ancestorsOnly ? [index.parents] : [index.parents, index.children]) {
    const visited = new Set(seeds);
    const pending = [...visited];
    while (pending.length) {
      const key = pending.pop()!;
      for (const next of direction.get(key) ?? []) {
        if (visited.has(next)) continue;
        visited.add(next);
        related.add(next);
        pending.push(next);
      }
    }
  }
  return related;
}

import {
  MINDMAP_SIDE_ANCHOR_SPAN, mindmapConnectionGeometry,
  type MindmapAttachments, type MindmapRectangle, type MindmapRouting, type MindmapSide
} from './mindmapGeometry';

type PortNode = MindmapRectangle & { key: string };
type PortEdge = { from: string; to: string };
type Endpoint = { index: number; end: 'from' | 'to'; side: MindmapSide; position: number; opposite: string };

/** Allocate once per graph, never per motion frame. Opposite-node order prevents crossed fans. */
export function mindmapEdgeAttachments(
  nodes: readonly PortNode[], edges: readonly PortEdge[], routing: MindmapRouting = 'horizontal'
): (MindmapAttachments | undefined)[] {
  const assignments: (MindmapAttachments | undefined)[] = Array(edges.length);
  if (routing !== 'radial') return assignments;
  const byKey = new Map(nodes.map(node => [node.key, node]));
  const groups = new Map<string, Endpoint[]>();
  const add = (node: PortNode, other: PortNode, index: number, end: 'from' | 'to', side: MindmapSide) => {
    const key = JSON.stringify([node.key, side]);
    const group = groups.get(key) ?? [];
    group.push({ index, end, side, position: side === 'left' || side === 'right' ? other.y : other.x, opposite: other.key });
    groups.set(key, group);
  };
  edges.forEach((edge, index) => {
    const from = byKey.get(edge.from), to = byKey.get(edge.to);
    if (!from || !to) return;
    const connection = mindmapConnectionGeometry(from, to, routing);
    if (connection.fromSide) add(from, to, index, 'from', connection.fromSide);
    if (connection.toSide) add(to, from, index, 'to', connection.toSide);
  });
  for (const group of groups.values()) {
    if (group.length < 2) continue; // Single edges retain their natural projection.
    group.sort((a, b) => a.position - b.position
      || (a.opposite < b.opposite ? -1 : a.opposite > b.opposite ? 1 : 0) || a.index - b.index);
    group.forEach((endpoint, rank) => {
      const attachment = { side: endpoint.side, offset: -MINDMAP_SIDE_ANCHOR_SPAN / 2 + rank * MINDMAP_SIDE_ANCHOR_SPAN / (group.length - 1) };
      (assignments[endpoint.index] ??= {})[endpoint.end] = attachment;
    });
  }
  return assignments;
}

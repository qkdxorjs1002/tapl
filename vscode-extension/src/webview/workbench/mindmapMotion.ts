import type { MindmapCamera } from './mindmapCamera';
import type { MindmapConnection, MindmapPoint } from './mindmapGeometry';

export type MindmapView = { left: number; right: number; top: number; bottom: number };
export const MINDMAP_PULSE_LIMIT = 24;
export const MINDMAP_DECORATION_INTERVAL = 1000 / 30;
const radius = 280;
const zero = { x: 0, y: 0 };

export function mindmapWorldView(camera: MindmapCamera, viewport: { width: number; height: number }, margin = 0): MindmapView {
  return {
    left: (-viewport.width / 2 - camera.x - margin) / camera.zoom,
    right: (viewport.width / 2 - camera.x + margin) / camera.zoom,
    top: (-viewport.height / 2 - camera.y - margin) / camera.zoom,
    bottom: (viewport.height / 2 - camera.y + margin) / camera.zoom
  };
}

/** The control hull contains the complete cubic, including edges whose nodes are offscreen. */
export function mindmapConnectionBounds(connection: MindmapConnection): MindmapView {
  const points = [connection.start, connection.control1, connection.control2, connection.end];
  return {
    left: Math.min(...points.map((point) => point.x)),
    right: Math.max(...points.map((point) => point.x)),
    top: Math.min(...points.map((point) => point.y)),
    bottom: Math.max(...points.map((point) => point.y))
  };
}

export function mindmapIntersects(a: MindmapView, b: MindmapView): boolean {
  return a.left <= b.right && a.right >= b.left && a.top <= b.bottom && a.bottom >= b.top;
}

/** Keep a deterministic, evenly distributed budget when a zoomed-out view contains many edges. */
export function mindmapVisiblePulses(edgeBounds: readonly MindmapView[], view: MindmapView, limit = MINDMAP_PULSE_LIMIT, eligible?: readonly boolean[]): number[] {
  const visible: number[] = [];
  edgeBounds.forEach((bounds, index) => {
    if ((!eligible || eligible[index]) && mindmapIntersects(bounds, view)) visible.push(index);
  });
  const count = Math.max(0, Math.floor(limit));
  if (visible.length <= count) return visible;
  return Array.from({ length: count }, (_, index) => visible[Math.floor(index * visible.length / count)]);
}

/** Build once per graph; pointer movement only visits nearby cells, regardless of the graph extent. */
export function mindmapNearbyNodes(nodes: readonly MindmapPoint[]) {
  const cells = new Map<string, number[]>();
  nodes.forEach((node, index) => {
    const key = `${Math.floor(node.x / radius)}:${Math.floor(node.y / radius)}`;
    const cell = cells.get(key);
    if (cell) cell.push(index);
    else cells.set(key, [index]);
  });
  return (point: MindmapPoint): number[] => {
    const x = Math.floor(point.x / radius), y = Math.floor(point.y / radius);
    const nearby: number[] = [];
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      const cell = cells.get(`${x + dx}:${y + dy}`);
      if (cell) for (const index of cell) nearby.push(index);
    }
    return nearby;
  };
}

/** Quantization prevents imperceptible settling from rewriting node and edge geometry forever. */
export function mindmapMagneticOffset(node: MindmapPoint, pointer: MindmapPoint, enabled = true): MindmapPoint {
  if (!enabled) return zero;
  const dx = pointer.x - node.x, dy = pointer.y - node.y;
  const influence = Math.max(0, 1 - Math.hypot(dx, dy) / radius);
  const quantize = (value: number) => Math.round(Math.max(-3, Math.min(3, value / 35)) * influence * 50) / 50 || 0;
  return { x: quantize(dx), y: quantize(dy) };
}

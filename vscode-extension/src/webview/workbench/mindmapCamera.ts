export type MindmapBounds = { minX: number; minY: number; maxX: number; maxY: number };
type Viewport = { width: number; height: number };
export type MindmapCamera = { x: number; y: number; zoom: number };
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));

/** Zooming out stops once the graph fits, while a lone node stays readable. */
export function mindmapMinimumZoom(bounds: MindmapBounds, viewport: Viewport): number {
  return clamp(
    Math.min(
      (Math.max(1, viewport.width) - 64) / Math.max(1, bounds.maxX - bounds.minX),
      (Math.max(1, viewport.height) - 96) / Math.max(1, bounds.maxY - bounds.minY),
      0.72
    ),
    0.08,
    0.72
  );
}

/** Keep the graph edges within a small overscroll margin; retain origin-centered views. */
export function constrainMindmapCamera(
  camera: MindmapCamera, bounds: MindmapBounds, viewport: Viewport,
  minimumZoom = mindmapMinimumZoom(bounds, viewport)
): MindmapCamera {
  const zoom = clamp(camera.zoom, minimumZoom, 2.8);
  const axis = (value: number, min: number, max: number, size: number) => {
    const margin = clamp(size * 0.1, 32, 96);
    const lo = Math.min(-margin, size / 2 - max * zoom - margin);
    const hi = Math.max(margin, -size / 2 - min * zoom + margin);
    return clamp(value, lo, hi);
  };
  return {
    x: axis(camera.x, bounds.minX, bounds.maxX, viewport.width),
    y: axis(camera.y, bounds.minY, bounds.maxY, viewport.height),
    zoom
  };
}

/** Drag distances are CSS pixels, independent of the current graph zoom. */
export const MINDMAP_FOLLOW_DRAG_THRESHOLD = 24;
export const MINDMAP_FOLLOW_DRAG_RESISTANCE = 0.18;
export function mindmapFollowDrag(x: number, y: number): { x: number; y: number; released: boolean } {
  const distance = Math.hypot(x, y);
  const released = distance > MINDMAP_FOLLOW_DRAG_THRESHOLD;
  // The continuous curve retains the small elastic offset when free panning begins.
  const scale = released
    ? 1 - MINDMAP_FOLLOW_DRAG_THRESHOLD * (1 - MINDMAP_FOLLOW_DRAG_RESISTANCE) / distance
    : MINDMAP_FOLLOW_DRAG_RESISTANCE;
  return { x: x * scale, y: y * scale, released };
}

type FollowNode = { x: number; y: number; width: number; height: number };
/** Center executing TASK boundaries, reducing the normal zoom only when the group needs room. */
export function mindmapFollowCamera(nodes: FollowNode[], viewport: Viewport): MindmapCamera {
  const normalZoom = clamp(Math.min((viewport.width - 72) / 1440, (viewport.height - 160) / 600), 0.72, 1);
  if (!nodes.length) return { x: 0, y: 0, zoom: normalZoom };
  const minX = Math.min(...nodes.map(node => node.x - node.width / 2));
  const maxX = Math.max(...nodes.map(node => node.x + node.width / 2));
  const minY = Math.min(...nodes.map(node => node.y - node.height / 2));
  const maxY = Math.max(...nodes.map(node => node.y + node.height / 2));
  const zoom = Math.min(normalZoom,
    Math.max(1, viewport.width - 96) / Math.max(1, maxX - minX),
    Math.max(1, viewport.height - 160) / Math.max(1, maxY - minY));
  return { x: -(minX + maxX) / 2 * zoom, y: -(minY + maxY) / 2 * zoom, zoom };
}

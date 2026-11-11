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
export function constrainMindmapCamera(camera: MindmapCamera, bounds: MindmapBounds, viewport: Viewport): MindmapCamera {
  const zoom = clamp(camera.zoom, mindmapMinimumZoom(bounds, viewport), 2.8);
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

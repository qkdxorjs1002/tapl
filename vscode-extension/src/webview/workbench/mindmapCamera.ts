import { mindmapFollowPan } from './mindmapFollowGesture';
export { MINDMAP_FOLLOW_DRAG_THRESHOLD, MINDMAP_FOLLOW_RESISTANCE as MINDMAP_FOLLOW_DRAG_RESISTANCE } from './mindmapFollowGesture';
export type MindmapBounds = { minX: number; minY: number; maxX: number; maxY: number };
type Viewport = { width: number; height: number };
export type MindmapCamera = { x: number; y: number; zoom: number };

/** Exact spring motion with a quick elastic rebound, independent of display refresh rate. */
export function mindmapSpringCamera(camera: MindmapCamera, target: MindmapCamera, velocity: MindmapCamera, elapsed: number) {
  const dt = Number.isFinite(elapsed) ? Math.max(0, Math.min(.05, elapsed)) : 0;
  if (!dt) return { camera: { ...camera }, velocity: { ...velocity } };
  const omega = 26, damping = omega * .58, frequency = omega * Math.sqrt(1 - .58 ** 2);
  const decay = Math.exp(-damping * dt), cosine = Math.cos(frequency * dt), sine = Math.sin(frequency * dt);
  const next = { ...camera }, speed = { ...velocity };
  for (const axis of ['x', 'y', 'zoom'] as const) {
    // Zoom rebounds in log space so even a large live retarget cannot invert the map.
    const logarithmic = axis === 'zoom';
    const current = logarithmic ? Math.log(camera.zoom) : camera[axis];
    const destination = logarithmic ? Math.log(target.zoom) : target[axis];
    const initialSpeed = logarithmic ? velocity.zoom / camera.zoom : velocity[axis];
    const distance = current - destination, impulse = (initialSpeed + damping * distance) / frequency;
    const position = destination + (distance * cosine + impulse * sine) * decay;
    const axisSpeed = ((-damping * distance + frequency * impulse) * cosine
      - (damping * impulse + frequency * distance) * sine) * decay;
    next[axis] = logarithmic ? Math.exp(position) : position;
    speed[axis] = logarithmic ? next.zoom * axisSpeed : axisSpeed;
  }
  return { camera: next, velocity: speed };
}
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
export function mindmapFollowDrag(x: number, y: number): { x: number; y: number; released: boolean } {
  return mindmapFollowPan(x, y);
}

type FollowNode = { x: number; y: number; width: number; height: number };
/** Fit executing TASKs and their PLAN context, with padding that adapts to small views. */
export function mindmapFollowCamera(nodes: FollowNode[], viewport: Viewport): MindmapCamera {
  const normalZoom = clamp(Math.min((viewport.width - 72) / 1440, (viewport.height - 160) / 600), 0.72, 1);
  if (!nodes.length) return { x: 0, y: 0, zoom: normalZoom };
  const minX = Math.min(...nodes.map(node => node.x - node.width / 2));
  const maxX = Math.max(...nodes.map(node => node.x + node.width / 2));
  const minY = Math.min(...nodes.map(node => node.y - node.height / 2));
  const maxY = Math.max(...nodes.map(node => node.y + node.height / 2));
  const padX = clamp(viewport.width * 0.08, 16, 64);
  const padY = clamp(viewport.height * 0.12, 24, 88);
  const zoom = Math.min(1.6,
    Math.max(1, viewport.width - padX * 2) / Math.max(1, maxX - minX),
    Math.max(1, viewport.height - padY * 2) / Math.max(1, maxY - minY));
  return { x: -(minX + maxX) / 2 * zoom, y: -(minY + maxY) / 2 * zoom, zoom };
}

type FollowRecord = { key: string; kind: string; status?: string; parent?: string };
/** Use resolved graph parents: stable IDs alone cannot identify a source-safe PLAN. */
export function mindmapRunFollowKeys(nodes: FollowRecord[], status?: string): string[] | undefined {
  if (status !== 'active') return undefined;
  const tasks = nodes.filter(node => node.kind === 'task' && node.status === 'In Progress');
  if (!tasks.length) return nodes.filter(node => node.kind === 'plan' && node.status === 'In Progress').map(node => node.key);
  const byKey = new Map(nodes.map(node => [node.key, node]));
  const keys = new Set(tasks.map(node => node.key));
  for (const task of tasks) {
    const parent = task.parent && byKey.get(task.parent);
    if (parent && parent.kind === 'plan') keys.add(parent.key);
  }
  return [...keys];
}

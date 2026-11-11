export type MindmapPoint = { x: number; y: number };
export type MindmapRectangle = MindmapPoint & { width: number; height: number };
export type MindmapRouting = 'horizontal' | 'radial';
export type MindmapConnection = {
  start: MindmapPoint;
  end: MindmapPoint;
  control1: MindmapPoint;
  control2: MindmapPoint;
  middle: number;
  path: string;
};

const zero = { x: 0, y: 0 };

/** Intersect a center ray with the rectangle, keeping its outgoing side normal. */
function boundary(rectangle: MindmapRectangle, direction: MindmapPoint) {
  const halfWidth = Math.max(0, rectangle.width) / 2;
  const halfHeight = Math.max(0, rectangle.height) / 2;
  const across = direction.x ? halfWidth / Math.abs(direction.x) : Infinity;
  const down = direction.y ? halfHeight / Math.abs(direction.y) : Infinity;
  const distance = Math.min(across, down);
  return {
    point: { x: rectangle.x + direction.x * distance, y: rectangle.y + direction.y * distance },
    normal: across <= down ? { x: Math.sign(direction.x), y: 0 } : { x: 0, y: Math.sign(direction.y) }
  };
}

/** Nodes use center coordinates. Offsets are applied before routing so moving edges stay attached. */
export function mindmapConnectionGeometry(
  from: MindmapRectangle,
  to: MindmapRectangle,
  routing: MindmapRouting = 'horizontal',
  fromOffset: MindmapPoint = zero,
  toOffset: MindmapPoint = zero
): MindmapConnection {
  const source = { ...from, x: from.x + fromOffset.x, y: from.y + fromOffset.y };
  const target = { ...to, x: to.x + toOffset.x, y: to.y + toOffset.y };
  let start: MindmapPoint, end: MindmapPoint, control1: MindmapPoint, control2: MindmapPoint;
  if (routing === 'radial') {
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    // Coincident centers still get deterministic, finite boundary anchors.
    const direction = dx || dy ? { x: dx, y: dy } : { x: 1, y: 0 };
    const outgoing = boundary(source, direction);
    const incoming = boundary(target, { x: -direction.x, y: -direction.y });
    start = outgoing.point;
    end = incoming.point;
    const handle = Math.min(160, Math.hypot(end.x - start.x, end.y - start.y) * 0.45);
    control1 = { x: start.x + outgoing.normal.x * handle, y: start.y + outgoing.normal.y * handle };
    control2 = { x: end.x + incoming.normal.x * handle, y: end.y + incoming.normal.y * handle };
  } else {
    // Preserve RUN's original horizontal anchors and exact SVG serialization.
    const direction = to.x >= from.x ? 1 : -1;
    start = { x: from.x + (from.width / 2) * direction + fromOffset.x, y: source.y };
    end = { x: to.x - (to.width / 2) * direction + toOffset.x, y: target.y };
    const middle = (start.x + end.x) / 2;
    control1 = { x: middle, y: start.y };
    control2 = { x: middle, y: end.y };
  }
  return {
    start,
    end,
    control1,
    control2,
    middle: (start.x + end.x) / 2,
    path: `M ${start.x} ${start.y} C ${control1.x} ${control1.y}, ${control2.x} ${control2.y}, ${end.x} ${end.y}`
  };
}

export function mindmapConnectionPoint(connection: MindmapConnection, progress: number): MindmapPoint {
  const { start, control1, control2, end } = connection;
  const p = progress,
    q = 1 - p;
  return {
    x: q * q * q * start.x + 3 * q * q * p * control1.x + 3 * q * p * p * control2.x + p * p * p * end.x,
    y: q * q * q * start.y + 3 * q * q * p * control1.y + 3 * q * p * p * control2.y + p * p * p * end.y
  };
}

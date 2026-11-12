/** Intent thresholds are screen-space values, independent of graph zoom. */
export const MINDMAP_FOLLOW_DRAG_THRESHOLD = 220;
export const MINDMAP_FOLLOW_TRACKPAD_THRESHOLD = MINDMAP_FOLLOW_DRAG_THRESHOLD;
export const MINDMAP_FOLLOW_WHEEL_THRESHOLD = 1200;
export const MINDMAP_FOLLOW_RESISTANCE = 0.6;
export const MINDMAP_FOLLOW_ZOOM_THRESHOLD = Math.log(1.65);
export const MINDMAP_FOLLOW_WHEEL_IDLE = 180;

const finite = (value: number) => Number.isFinite(value) ? Math.max(-1e6, Math.min(1e6, value)) : 0;

/** Soft at first, increasingly resistant as it bends; release retains that offset. */
export function mindmapFollowPan(x: number, y: number, threshold = MINDMAP_FOLLOW_DRAG_THRESHOLD) {
  x = finite(x); y = finite(y);
  const distance = Math.hypot(x, y);
  const released = distance > threshold;
  const elastic = -threshold * MINDMAP_FOLLOW_RESISTANCE * Math.expm1(-Math.min(distance, threshold) / threshold);
  const scale = distance ? (elastic + Math.max(0, distance - threshold)) / distance : 0;
  return { x: x * scale, y: y * scale, released };
}

/** Log scale treats expansion and contraction symmetrically and allows reversals. */
export function mindmapFollowZoom(logScale: number) {
  const value = finite(logScale);
  const offset = mindmapFollowPan(value, 0, MINDMAP_FOLLOW_ZOOM_THRESHOLD);
  return { factor: Math.exp(Math.max(-20, Math.min(20, offset.x))), released: offset.released };
}

export type MindmapFollowWheel = {
  x: number; y: number; time: number;
  pan?: { dx: number; dy: number; speed: number; peak: number; slowing: number; momentum: boolean };
};
/** Net movement within one continuous burst; idle gaps never accumulate intent. */
export function mindmapFollowWheel(previous: MindmapFollowWheel | undefined, x: number, y: number, time: number) {
  const continuous = previous && time >= previous.time && time - previous.time < MINDMAP_FOLLOW_WHEEL_IDLE;
  const timestamp = Number.isFinite(time) ? time : 0;
  return { x: finite((continuous ? previous.x : 0) + finite(x)), y: finite((continuous ? previous.y : 0) + finite(y)),
    time: timestamp };
}

/** Pixel wheel deltas already contain OS acceleration. Compress speed without adding input latency. */
export function mindmapFollowTrackpad(previous: MindmapFollowWheel | undefined, x: number, y: number, time: number, momentum?: boolean): MindmapFollowWheel {
  x = finite(x); y = finite(y);
  const timestamp = Number.isFinite(time) ? time : 0;
  const continuous = previous && timestamp >= previous.time && timestamp - previous.time < MINDMAP_FOLLOW_WHEEL_IDLE;
  const before = continuous ? previous : undefined, pan = before?.pan;
  const elapsed = pan ? Math.max(4, Math.min(40, timestamp - before!.time)) : 1000 / 60;
  const distance = Math.hypot(x, y), speed = distance / elapsed;
  const redirected = !!pan && x * pan.dx + y * pan.dy < .5 * distance * Math.hypot(pan.dx, pan.dy);
  const resumed = !!pan?.momentum && (momentum === false || (momentum === undefined
    && ((redirected && distance > 2) || (speed > pan.speed * 1.8 && speed > .12 && distance > 2))));
  const motionContinues = pan !== undefined && !redirected && !resumed;
  const history = motionContinues && pan.peak > 0;
  const filtered = history ? pan.speed + (speed - pan.speed) * -Math.expm1(-elapsed / 24) : speed;
  // The first packet has no measured cadence, so it must not seed deceleration detection.
  const peak = motionContinues ? Math.max(pan.peak, filtered) : 0;
  const slowing = history && filtered < pan.speed * .98 ? pan.slowing + elapsed : 0;
  // Prefer the platform phase. Older browsers need a conservative, sustained deceleration fallback.
  const tail = momentum ?? (!!pan?.momentum && !resumed || peak > .4 && filtered < peak * .6 && slowing >= 40);
  const inputSpeed = resumed ? distance / (1000 / 60) : speed;
  const gain = 1 / Math.sqrt(1 + (inputSpeed / 3) ** 2);
  const base = resumed ? undefined : before;
  return {
    x: finite((base?.x ?? 0) + (tail ? 0 : x * gain)),
    y: finite((base?.y ?? 0) + (tail ? 0 : y * gain)), time: timestamp,
    pan: { dx: x, dy: y, speed: filtered, peak, slowing, momentum: tail }
  };
}

/** Translate trackpad travel into a long, soft elastic stroke in screen space. */
export function mindmapFollowWheelResponse(state: MindmapFollowWheel, zoom = false) {
  if (zoom) {
    return { x: 0, y: 0, ...mindmapFollowZoom(state.y * 0.008) };
  }
  const offset = mindmapFollowPan(state.x, state.y, MINDMAP_FOLLOW_WHEEL_THRESHOLD);
  const released = state.pan
    ? !state.pan.momentum && Math.hypot(state.x, state.y) > MINDMAP_FOLLOW_TRACKPAD_THRESHOLD
    : offset.released;
  return { x: offset.x * .35, y: offset.y * .35, factor: 1, released };
}

/** Wheel delta modes use the same CSS-pixel units for intent and manual movement. */
export function mindmapWheelDelta(x: number, y: number, mode: number, height: number, shift = false) {
  const unit = mode === 1 ? 18 : mode === 2 ? Math.max(1, finite(height)) : 1;
  const horizontal = shift && x === 0;
  return { x: finite(finite(horizontal ? y : x) * unit), y: finite((horizontal ? 0 : finite(y)) * unit) };
}

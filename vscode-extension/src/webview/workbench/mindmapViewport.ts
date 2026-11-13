import { useEffect, useMemo, useRef, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { constrainMindmapCamera, mindmapMinimumZoom, mindmapFollowCamera, mindmapFollowDrag, mindmapSpringCamera } from './mindmapCamera';
import type { MindmapBounds, MindmapCamera } from './mindmapCamera';
import {
  mindmapFollowPan, mindmapFollowZoom, mindmapFollowWheel, mindmapFollowTrackpad, mindmapFollowWheelResponse, mindmapWheelDelta,
  MINDMAP_FOLLOW_WHEEL_IDLE
} from './mindmapFollowGesture';
import type { MindmapFollowWheel } from './mindmapFollowGesture';
import { mindmapConnectionGeometry } from './mindmapGeometry';
import type { MindmapRouting } from './mindmapGeometry';
import {
  MINDMAP_DECORATION_INTERVAL,
  mindmapConnectionBounds,
  mindmapIntersects,
  mindmapMagneticOffset,
  mindmapNearbyNodes,
  mindmapPulseLookup,
  mindmapWorldView
} from './mindmapMotion';
import { useMindmapValue } from './useMindmapCache';

/** Layout and optional execution flags shared by RUN trees and associative memory DAGs. */
export type MindmapViewportGraph = {
  nodes: { key: string; x: number; y: number; width: number; height: number }[];
  edges: { from: string; to: string; flowing?: boolean }[];
  bounds: MindmapBounds;
  routing?: MindmapRouting;
};
export type MindmapViewportControls = { fit: () => void; zoom: (factor: number) => void; toggleFollow: () => void; focus: (key: string) => void };
type Camera = MindmapCamera;
type Point = { x: number; y: number };
type ElasticDrag = { origin: Point; base: Camera };
type ElasticZoom = { base: Camera; point: Point; logScale: number; x: number; y: number };
type ReturnMotion = { velocity: Camera; time: number };
type ViewportInteraction = {
  key: string; tracking: boolean; target: Camera; camera: Camera; velocity: Camera; frameTime?: number;
  returnMotion?: ReturnMotion; pointerInside: boolean; pointer: Point; lastPointer: Point;
  gestureScale: number; gestureActive: boolean; dragged: boolean; lastNativeGesture: number;
  touches: Set<number>; pointers: Map<number, Point>; elastic?: ElasticDrag; elasticZoom?: ElasticZoom;
  wheelIntent?: MindmapFollowWheel; wheelBase?: Camera; wheelKind?: 'pan' | 'zoom';
  lastWheelTime: number;
  anchor?: Point; pinch?: { distance: number; center: Point };
};
const cameras = new Map<string, Camera>();
// Preferences survive record navigation, but a webview reload starts active RUNs following again.
const followPreferences = new Map<string, boolean>();
const clamp = (n: number, min: number, max: number) => Math.max(min, Math.min(max, n));

/** Shared camera, gestures, focus visibility, and synchronized 2D edge motion. */
export function useMindmapViewport({
  graph: incomingGraph,
  cameraKey,
  follow: incomingFollow,
  setActive
}: {
  graph: MindmapViewportGraph;
  cameraKey: string;
  /** Present only for active RUNs; an empty list follows the default RUN view. */
  follow?: string[];
  setActive: (key?: string) => void;
}) {
  // Labels, bodies and navigation payloads can change without invalidating geometry or gestures.
  const graph = useMindmapValue(useMemo<MindmapViewportGraph>(() => ({
    nodes: incomingGraph.nodes.map(({ key, x, y, width, height }) => ({ key, x, y, width, height })),
    edges: incomingGraph.edges.map(({ from, to, flowing }) => ({ from, to, ...(flowing === undefined ? {} : { flowing }) })),
    bounds: incomingGraph.bounds,
    routing: incomingGraph.routing
  }), [incomingGraph]));
  const follow = useMindmapValue(incomingFollow);
  const hostRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<HTMLDivElement>(null);
  const controlsRef = useRef<MindmapViewportControls>();
  const interactionRef = useRef<ViewportInteraction>();
  const suppressClickRef = useRef(0);
  // Keep blur state across graph-effect replacements, including synthetic host blur events.
  const focusedRef = useRef(typeof document === 'undefined' || document.hasFocus());
  const [, updateFollow] = useState(0);
  const following = follow !== undefined && (followPreferences.get(cameraKey) ?? true);
  const byKey = useMemo(() => new Map(graph.nodes.map((node) => [node.key, node])), [graph]);
  const edges = useMemo(
    () =>
      graph.edges.flatMap((edge, index) => {
        const from = byKey.get(edge.from),
          to = byKey.get(edge.to);
        if (!from || !to) return [];
        return [
          {
            ...edge,
            index,
            ...mindmapConnectionGeometry(from, to, graph.routing)
          }
        ];
      }),
    [graph, byKey]
  );

  useEffect(() => {
    const host = hostRef.current,
      canvas = worldRef.current;
    if (!host || !canvas) return;
    let bounds = host.getBoundingClientRect();
    let tracking = follow !== undefined && (followPreferences.get(cameraKey) ?? true);
    const saved = interactionRef.current;
    // Data refreshes rebuild graph caches, not the user's ongoing interaction.
    const resume = follow !== undefined && saved?.key === cameraKey && saved.tracking === tracking ? saved : undefined;
    let target: Camera = { ...(resume?.target ?? cameras.get(cameraKey) ?? { x: 0, y: 0, zoom: 1 }) };
    if (!tracking && !(resume?.pointers.size || resume?.gestureActive || (resume && performance.now() - resume.lastWheelTime < MINDMAP_FOLLOW_WHEEL_IDLE)))
      target = constrainMindmapCamera(target, graph.bounds, bounds);
    let camera = { ...(resume?.camera ?? target) };
    let cameraVelocity: Camera = { ...(resume?.velocity ?? { x: 0, y: 0, zoom: 0 }) }, previousFrameTime = resume?.frameTime;
    let returnMotion: ReturnMotion | undefined = resume?.returnMotion;
    let raf = 0,
      ambientTimer = 0,
      disposed = false,
      onScreen = true,
      pointerInside = resume?.pointerInside ?? false;
    let pointer: Point = resume?.pointer ?? { x: bounds.width / 2, y: bounds.height / 2 };
    let lastPointer = { ...(resume?.lastPointer ?? pointer) };
    let gestureScale = resume?.gestureScale ?? 1,
      gestureActive = resume?.gestureActive ?? false,
      dragged = resume?.dragged ?? false,
      lastNativeGesture = resume?.lastNativeGesture ?? 0;
    const touchPointers = new Set(resume?.touches);
    const pointers = new Map(resume?.pointers);
    let elastic: ElasticDrag | undefined = resume?.elastic;
    let elasticZoom: ElasticZoom | undefined = resume?.elasticZoom;
    let wheelIntent = resume?.wheelIntent, wheelBase = resume?.wheelBase;
    let wheelKind = resume?.wheelKind, wheelTimer = 0;
    let lastWheelTime = resume?.lastWheelTime ?? -Infinity;
    let anchor = resume?.anchor, pinch = resume?.pinch;
    host.classList.toggle('wb-mm-dragging', pointers.size > 0 && dragged);
    host.classList.toggle('wb-mm-pointer-inside', pointerInside);
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let reduced = motion.matches;
    const nodeElements = Array.from(canvas.querySelectorAll<HTMLElement>('[data-mindmap-node]'));
    const pulses = Array.from(canvas.querySelectorAll<SVGGElement>('.wb-mm-pulse'));
    const paths = Array.from(canvas.querySelectorAll<SVGPathElement>('.wb-mm-edge'));
    const glassPaths = paths.map((path) => Array.from(path.parentElement?.querySelectorAll<SVGPathElement>('.wb-mm-glass-path') ?? []));
    const eligiblePulses = edges.map((edge) => edge.flowing === true);
    const setPath = (index: number, value: string) => {
      for (const path of [paths[index], ...glassPaths[index]]) {
        if (path && path.getAttribute('d') !== value) path.setAttribute('d', value);
      }
    };
    const hidePulse = (index: number) => {
      if (pulses[index]) pulses[index].style.opacity = '0';
    };
    // React can retain imperative styles across an effect restart; restore the current graph once.
    nodeElements.forEach((element, index) => {
      const node = graph.nodes[index];
      if (!node) return;
      const value = `translate(${node.x - node.width / 2}px, ${node.y - node.height / 2}px)`;
      if (element.style.transform !== value) element.style.transform = value;
    });
    edges.forEach((edge, index) => setPath(index, edge.path));
    const pointerLight = host.querySelector<HTMLElement>('.wb-mm-pointer-light');
    pointerLight?.style.setProperty('--mm-px', `${lastPointer.x}px`);
    pointerLight?.style.setProperty('--mm-py', `${lastPointer.y}px`);
    const nodeIndices = new Map(graph.nodes.map((node, index) => [node.key, index]));
    const nearbyNodes = mindmapNearbyNodes(graph.nodes);
    const edgeBounds = edges.map(mindmapConnectionBounds);
    const visiblePulses = mindmapPulseLookup(edgeBounds, eligiblePulses);
    const incident = new Map<string, number[]>();
    edges.forEach((edge, index) => {
      for (const key of [edge.from, edge.to]) {
        const list = incident.get(key);
        if (list) list.push(index);
        else incident.set(key, [index]);
      }
    });
    const offsets = new Map<number, Point>();
    let pulseIndices: number[] = [], decorationDirty = true, viewDirty = true;
    let lastDecoration = -Infinity;
    let renderedCamera: Camera | undefined;
    const remember = () => {
      cameras.delete(cameraKey);
      cameras.set(cameraKey, { ...target });
      if (cameras.size > 24) cameras.delete(cameras.keys().next().value!);
    };
    const visible = () => !disposed && focusedRef.current && onScreen && !document.hidden;
    const transform = () => {
      if (renderedCamera && renderedCamera.x === camera.x && renderedCamera.y === camera.y && renderedCamera.zoom === camera.zoom) return false;
      canvas.style.transform = `translate(${camera.x}px, ${camera.y}px) scale(${camera.zoom})`;
      if (!renderedCamera || renderedCamera.x !== camera.x || renderedCamera.y !== camera.y)
        host.style.backgroundPosition = `${camera.x}px ${camera.y}px`;
      if (!renderedCamera || renderedCamera.zoom !== camera.zoom)
        host.style.backgroundSize = `${26 * camera.zoom}px ${26 * camera.zoom}px`;
      renderedCamera = { ...camera };
      return true;
    };
    const tick = (time: number) => {
      raf = 0;
      if (!visible()) return;
      const previous = { ...camera };
      const elapsed = previousFrameTime === undefined ? 1 / 60 : Math.max(.001, Math.min(.05, (time - previousFrameTime) / 1000));
      previousFrameTime = time;
      if (returnMotion && !reduced) {
        const next = mindmapSpringCamera(camera, target, returnMotion.velocity, (time - returnMotion.time) / 1000);
        camera = next.camera;
        returnMotion = { velocity: next.velocity, time };
        cameraVelocity = next.velocity;
        if (Math.abs(camera.x - target.x) < .02 && Math.abs(camera.y - target.y) < .02
          && Math.abs(camera.zoom - target.zoom) < .00001 && Math.abs(next.velocity.x) < .3
          && Math.abs(next.velocity.y) < .3 && Math.abs(next.velocity.zoom) < .0001) {
          camera = { ...target };
          cameraVelocity = { x: 0, y: 0, zoom: 0 };
          returnMotion = undefined;
        }
      } else {
        returnMotion = undefined;
        const directPan = tracking && wheelKind === 'pan' && wheelIntent && !wheelIntent.pan?.momentum;
        const easing = reduced || pointers.size || directPan ? 1 : 0.18;
        camera.x += (target.x - camera.x) * easing;
        camera.y += (target.y - camera.y) * easing;
        camera.zoom += (target.zoom - camera.zoom) * easing;
        if (Math.abs(target.x - camera.x) < 0.05) camera.x = target.x;
        if (Math.abs(target.y - camera.y) < 0.05) camera.y = target.y;
        if (Math.abs(target.zoom - camera.zoom) < 0.0001) camera.zoom = target.zoom;
        for (const axis of ['x', 'y', 'zoom'] as const) cameraVelocity[axis] = (camera[axis] - previous[axis]) / elapsed;
      }
      const cameraChanged = transform();
      let pointerChanged = false;
      for (const axis of ['x', 'y'] as const) {
        const previous = lastPointer[axis];
        lastPointer[axis] += (pointer[axis] - lastPointer[axis]) * (reduced ? 1 : 0.16);
        if (Math.abs(pointer[axis] - lastPointer[axis]) < 0.05) lastPointer[axis] = pointer[axis];
        if (previous !== lastPointer[axis]) {
          pointerLight?.style.setProperty(axis === 'x' ? '--mm-px' : '--mm-py', `${lastPointer[axis]}px`);
          pointerChanged = true;
        }
      }
      decorationDirty ||= cameraChanged || pointerChanged;
      viewDirty ||= cameraChanged;
      const cameraMoving = !!returnMotion || camera.x !== target.x || camera.y !== target.y || camera.zoom !== target.zoom;
      const pointerMoving = lastPointer.x !== pointer.x || lastPointer.y !== pointer.y;
      // Camera and pointer light keep their native frame rate; graph decorations have a separate budget.
      if (time - lastDecoration >= MINDMAP_DECORATION_INTERVAL || reduced) {
        const view = mindmapWorldView(camera, bounds, 12);
        if (viewDirty) {
          const nextPulses = reduced ? [] : visiblePulses(view);
          const selected = new Set(nextPulses);
          for (const index of pulseIndices) if (!selected.has(index)) hidePulse(index);
          pulseIndices = nextPulses;
          viewDirty = false;
        }
        if (decorationDirty) {
          const worldPointer = {
            x: (lastPointer.x - bounds.width / 2 - camera.x) / camera.zoom,
            y: (lastPointer.y - bounds.height / 2 - camera.y) / camera.zoom
          };
          const magnetic = !reduced && pointerInside && !pointers.size;
          const candidates = new Set(magnetic ? nearbyNodes(worldPointer) : []);
          for (const index of offsets.keys()) candidates.add(index);
          const dirtyEdges = new Set<number>();
          for (const index of candidates) {
            const node = graph.nodes[index];
            const onscreen = mindmapIntersects(view, {
              left: node.x - node.width / 2, right: node.x + node.width / 2,
              top: node.y - node.height / 2, bottom: node.y + node.height / 2
            });
            const next = mindmapMagneticOffset(node, worldPointer, magnetic && onscreen);
            const previous = offsets.get(index);
            if ((previous?.x || 0) === next.x && (previous?.y || 0) === next.y) continue;
            if (next.x || next.y) offsets.set(index, next);
            else offsets.delete(index);
            const element = nodeElements[index];
            if (element) element.style.transform = `translate(${node.x - node.width / 2 + next.x}px, ${node.y - node.height / 2 + next.y}px)`;
            for (const edgeIndex of incident.get(node.key) || []) dirtyEdges.add(edgeIndex);
          }
          for (const index of dirtyEdges) {
            const edge = edges[index];
            const connection = mindmapConnectionGeometry(
              byKey.get(edge.from)!, byKey.get(edge.to)!, graph.routing,
              offsets.get(nodeIndices.get(edge.from)!), offsets.get(nodeIndices.get(edge.to)!)
            );
            setPath(index, connection.path);
          }
          decorationDirty = false;
        }
        for (const index of pulseIndices) {
          const pulse = pulses[index];
          if (!pulse || reduced) continue;
          const p = (time / 5200 + index * 0.173) % 1;
          const opacity = String(Math.sin(p * Math.PI) * 0.92);
          // Every light layer shares one normalized distance along the curve.
          pulse.style.setProperty('--mm-flow-progress', String(p * 100));
          pulse.style.opacity = opacity;
        }
        lastDecoration = time;
      }
      if (cameraMoving || pointerMoving)
        raf = requestAnimationFrame(tick);
      else if (decorationDirty || viewDirty || (!reduced && pulseIndices.length))
        ambientTimer = window.setTimeout(() => {
          ambientTimer = 0;
          tick(performance.now());
        }, Math.max(1, MINDMAP_DECORATION_INTERVAL - (performance.now() - lastDecoration)));
    };
    const wake = () => {
      if (ambientTimer) window.clearTimeout(ambientTimer);
      ambientTimer = 0;
      if (!raf && visible()) raf = requestAnimationFrame(tick);
    };
    const setTarget = (next: Camera, panning = false) => {
      returnMotion = undefined;
      const constrained = constrainMindmapCamera(next, graph.bounds, bounds,
        panning ? Math.min(target.zoom, mindmapMinimumZoom(graph.bounds, bounds)) : undefined);
      // An outer followed TASK can start beyond the normal pan limits. Move back toward
      // those limits continuously, retaining the current zoom and avoiding a release jump.
      target = panning ? {
        ...constrained,
        x: clamp(next.x, Math.min(target.x, constrained.x), Math.max(target.x, constrained.x)),
        y: clamp(next.y, Math.min(target.y, constrained.y), Math.max(target.y, constrained.y))
      } : constrained;
      remember();
      wake();
    };
    const followKeys = new Set(follow);
    const followedNodes = graph.nodes.filter(node => followKeys.has(node.key));
    const followTarget = () => mindmapFollowCamera(followedNodes, bounds);
    const track = (settle = false) => {
      target = followTarget(); // Following may center an outer leaf beyond normal pan constraints.
      returnMotion = undefined;
      if (settle && !reduced) {
        const velocity: Camera = { x: 0, y: 0, zoom: 0 };
        if (previousFrameTime !== undefined && performance.now() - previousFrameTime < 70) {
          for (const axis of ['x', 'y', 'zoom'] as const) {
            const limit = Math.abs(target[axis] - camera[axis]) * 4;
            velocity[axis] = clamp(cameraVelocity[axis], -limit, limit);
          }
        }
        returnMotion = { velocity, time: performance.now() };
      }
      remember();
      wake();
    };
    const clearWheel = () => {
      if (wheelTimer) window.clearTimeout(wheelTimer);
      wheelTimer = 0;
      wheelIntent = undefined;
      wheelBase = undefined;
      wheelKind = undefined;
    };
    const clearElastic = () => {
      clearWheel();
      elastic = undefined;
      elasticZoom = undefined;
    };
    const scheduleWheelReturn = () => {
      if (wheelTimer) window.clearTimeout(wheelTimer);
      if (!wheelIntent || !tracking) return;
      wheelTimer = window.setTimeout(() => {
        const returning = wheelIntent?.pan?.momentum;
        clearElastic();
        if (tracking) {
          if (returning) { target = followTarget(); remember(); wake(); }
          else track(true);
        }
      }, Math.max(0, MINDMAP_FOLLOW_WHEEL_IDLE - (performance.now() - wheelIntent.time)));
    };
    const setFollowing = (enabled: boolean) => {
      if (follow === undefined || tracking === enabled) return;
      tracking = enabled;
      followPreferences.delete(cameraKey);
      followPreferences.set(cameraKey, enabled);
      if (followPreferences.size > 24) followPreferences.delete(followPreferences.keys().next().value!);
      host.dataset.following = String(enabled);
      updateFollow(value => value + 1);
      clearElastic();
      returnMotion = undefined;
      if (enabled) track();
    };
    const manual = () => setFollowing(false);
    const fit = () => {
      const zoom = clamp(Math.min((bounds.width - 72) / 1440, (bounds.height - 160) / 600), 0.72, 1);
      setTarget({ x: 0, y: 0, zoom });
    };
    const zoomAt = (factor: number, point: Point) => {
      const minimum = mindmapMinimumZoom(graph.bounds, bounds);
      const zoom = clamp(target.zoom * factor, follow === undefined ? minimum : Math.min(target.zoom, minimum), 2.8),
        ratio = zoom / target.zoom;
      setTarget({ x: point.x - (point.x - target.x) * ratio, y: point.y - (point.y - target.y) * ratio, zoom },
        follow !== undefined);
    };
    const local = (x: number, y: number) => ({
      x: Number.isFinite(x) ? x - bounds.left - bounds.width / 2 : 0,
      y: Number.isFinite(y) ? y - bounds.top - bounds.height / 2 : 0
    });
    const center = () => ({ x: 0, y: 0 });
    const beginElasticZoom = (point: Point): ElasticZoom => ({ base: { ...target }, point, logScale: 0, x: 0, y: 0 });
    const applyElasticZoom = (state: ElasticZoom, wheelResponse?: { factor: number; released: boolean }) => {
      const zoom = wheelResponse ?? mindmapFollowZoom(state.logScale), pan = mindmapFollowPan(state.x, state.y);
      // A deliberate extreme pinch still obeys the manual zoom ceiling. Preserve
      // the anchor after clamping, including followed groups below the normal floor.
      const scale = clamp(state.base.zoom * zoom.factor,
        Math.min(state.base.zoom, mindmapMinimumZoom(graph.bounds, bounds)), 2.8);
      const ratio = scale / state.base.zoom;
      target = {
        x: state.point.x - (state.point.x - state.base.x) * ratio + pan.x,
        y: state.point.y - (state.point.y - state.base.y) * ratio + pan.y,
        zoom: scale
      };
      if (zoom.released || pan.released) manual();
      remember();
      wake();
    };
    controlsRef.current = {
      fit: () => { manual(); fit(); },
      zoom: (factor) => { manual(); zoomAt(factor, center()); },
      focus: (key) => {
        const node = byKey.get(key);
        if (!node) return;
        manual();
        const zoom = Math.min(1, mindmapFollowCamera([node], bounds).zoom);
        setTarget({ x: -node.x * zoom, y: -node.y * zoom, zoom });
        setActive(key);
      },
      toggleFollow: () => setFollowing(!tracking)
    };
    if (follow !== undefined) host.dataset.following = String(tracking);
    else delete host.dataset.following;
    const interacting = () => pointers.size > 0 || gestureActive || (!!wheelIntent && !wheelIntent.pan?.momentum)
      || (!tracking && performance.now() - lastWheelTime < MINDMAP_FOLLOW_WHEEL_IDLE);
    if (tracking) {
      if (!interacting()) {
        if (returnMotion) target = followTarget();
        else track();
      }
      if (wheelIntent) scheduleWheelReturn();
    }
    else if (!cameras.has(cameraKey)) {
      fit();
      camera = { ...target };
    }
    // A newly mounted world still needs its static fit while motion is suspended.
    if (!visible() && !resume && !canvas.style.transform) camera = { ...target };
    if (visible() || !canvas.style.transform) transform();
    const wheel = (event: WheelEvent) => {
      if ((event.target as Element).closest('[data-mm-controls]')) return;
      event.preventDefault();
      if (gestureActive || Date.now() - lastNativeGesture < 140) return;
      const delta = mindmapWheelDelta(event.deltaX, event.deltaY, event.deltaMode, bounds.height, event.shiftKey);
      const kind = event.ctrlKey || event.metaKey ? 'zoom' : 'pan';
      if (kind === 'zoom' ? !delta.y : !delta.x && !delta.y) return;
      const momentum = (event as WheelEvent & { momentum?: boolean }).momentum;
      if (tracking && kind === 'pan' && event.deltaMode === 0 && momentum === true && (wheelKind !== 'pan' || !wheelIntent)) return;
      const now = performance.now();
      lastWheelTime = now;
      if (tracking) {
        if (wheelKind !== kind || !wheelIntent || now - wheelIntent.time >= MINDMAP_FOLLOW_WHEEL_IDLE) {
          clearWheel();
          returnMotion = undefined;
          target = { ...camera };
          wheelBase = { ...target };
          wheelKind = kind;
          elastic = undefined;
          elasticZoom = kind === 'zoom' ? beginElasticZoom(local(event.clientX, event.clientY)) : undefined;
        }
        const previous = wheelIntent;
        wheelIntent = kind === 'pan' && event.deltaMode === 0
          ? mindmapFollowTrackpad(previous, -delta.x, -delta.y, now, momentum)
          : mindmapFollowWheel(previous, -delta.x, -delta.y, now);
        if (wheelIntent.pan?.momentum) {
          if (!previous?.pan?.momentum) track(true);
          scheduleWheelReturn();
          return;
        }
        if (previous?.pan?.momentum) {
          wheelBase = { ...camera };
          returnMotion = undefined;
        }
        const response = mindmapFollowWheelResponse(wheelIntent, kind === 'zoom');
        if (kind === 'zoom' && elasticZoom) {
          applyElasticZoom(elasticZoom, response);
        } else if (wheelBase) {
          target = { ...wheelBase, x: wheelBase.x + response.x, y: wheelBase.y + response.y };
          if (response.released) {
            if (event.deltaMode === 0) camera = { ...target };
            manual();
          }
          remember();
          wake();
        }
        if (tracking) scheduleWheelReturn();
        return;
      }
      if (kind === 'zoom')
        zoomAt(Math.exp(clamp(-delta.y * 0.008, -20, 20)), local(event.clientX, event.clientY));
      else {
        setTarget({
          ...target,
          x: target.x - delta.x,
          y: target.y - delta.y
        }, true);
      }
    };
    const resetGesture = () => {
      const spring = elastic || elasticZoom || wheelIntent;
      clearElastic();
      lastWheelTime = -Infinity;
      if (spring && tracking) track(true);
      pointers.clear();
      touchPointers.clear();
      pinch = undefined;
      anchor = undefined;
      gestureActive = false;
      host.classList.remove('wb-mm-dragging');
      decorationDirty = true;
    };
    const rebase = () => {
      const values = [...pointers.values()];
      anchor = values.length === 1 ? { ...values[0] } : undefined;
      pinch =
        values.length >= 2
          ? {
              distance: Math.max(1, Math.hypot(values[1].x - values[0].x, values[1].y - values[0].y)),
              center: { x: (values[0].x + values[1].x) / 2, y: (values[0].y + values[1].y) / 2 }
            }
          : undefined;
    };
    const down = (event: PointerEvent) => {
      host.dataset.inputMode = 'pointer';
      if (event.button !== 0 || !Number.isFinite(event.clientX) || !Number.isFinite(event.clientY)
        || (event.target as Element).closest('[data-mm-controls]')) return;
      if (!pointers.size) {
        if (tracking) {
          clearElastic();
          returnMotion = undefined;
          target = { ...camera };
        }
        dragged = false;
        camera = { ...target };
      }
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      decorationDirty = true;
      wake();
      if (event.pointerType === 'touch') touchPointers.add(event.pointerId);
      rebase();
      if (pointers.size >= 2) {
        elastic = undefined;
        if (tracking && pinch) elasticZoom = beginElasticZoom(local(pinch.center.x, pinch.center.y));
      }
      else if (tracking) elastic = { origin: { x: event.clientX, y: event.clientY }, base: { ...target } };
      // Capture on the original button so a stationary tap keeps normal record navigation.
      const element = event.target instanceof Element ? event.target : host;
      try {
        element.setPointerCapture(event.pointerId);
      } catch {
        /* A released pointer needs no capture. */
      }
      if (!(event.target as Element).closest('button,[data-mindmap-node]')) host.focus({ preventScroll: true });
    };
    const move = (event: PointerEvent) => {
      if (!Number.isFinite(event.clientX) || !Number.isFinite(event.clientY)) return;
      if (event.target instanceof Node && host.contains(event.target)) {
        if (!pointerInside) {
          decorationDirty = true;
          host.classList.add('wb-mm-pointer-inside');
        }
        pointerInside = true;
        pointer = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
        wake();
      }
      if (!pointers.has(event.pointerId)) return;
      const previous = pointers.get(event.pointerId)!;
      const next = { x: event.clientX, y: event.clientY };
      // Preserve the original anchor until a deliberate drag starts.
      if (pointers.size === 1 && !dragged && anchor && Math.hypot(next.x - anchor.x, next.y - anchor.y) < 5) return;
      pointers.set(event.pointerId, next);
      if (pointers.size >= 2 && pinch) {
        const values = [...pointers.values()];
        const current = {
          distance: Math.max(1, Math.hypot(values[1].x - values[0].x, values[1].y - values[0].y)),
          center: { x: (values[0].x + values[1].x) / 2, y: (values[0].y + values[1].y) / 2 }
        };
        if (tracking && elasticZoom) {
          elasticZoom.logScale += Math.log(current.distance / pinch.distance);
          elasticZoom.x += current.center.x - pinch.center.x;
          elasticZoom.y += current.center.y - pinch.center.y;
          applyElasticZoom(elasticZoom);
        } else {
          zoomAt(current.distance / pinch.distance, local(pinch.center.x, pinch.center.y));
          setTarget({
            ...target,
            x: target.x + current.center.x - pinch.center.x,
            y: target.y + current.center.y - pinch.center.y
          }, follow !== undefined);
        }
        pinch = current;
      } else if (elastic && tracking) {
        const offset = mindmapFollowDrag(next.x - elastic.origin.x, next.y - elastic.origin.y);
        target = { ...elastic.base, x: elastic.base.x + offset.x, y: elastic.base.y + offset.y };
        if (offset.released) { manual(); elastic = undefined; }
        remember();
        wake();
      } else {
        const origin = !dragged && anchor ? anchor : previous;
        setTarget({ ...target, x: target.x + next.x - origin.x, y: target.y + next.y - origin.y }, true);
      }
      dragged = true;
      suppressClickRef.current = Date.now() + 450;
      host.classList.add('wb-mm-dragging');
      event.preventDefault();
    };
    const up = (event: PointerEvent) => {
      if (!pointers.has(event.pointerId)) return;
      const spring = elastic || elasticZoom;
      pointers.delete(event.pointerId);
      if (spring && tracking && !pointers.size) track(true);
      clearElastic();
      decorationDirty = true;
      wake();
      touchPointers.delete(event.pointerId);
      if (dragged) suppressClickRef.current = Date.now() + 450;
      rebase(); // Pinch → one-finger drag starts at the remaining finger, with no jump.
      if (tracking && anchor) elastic = { origin: { ...anchor }, base: { ...target } };
      else if (tracking && pinch) elasticZoom = beginElasticZoom(local(pinch.center.x, pinch.center.y));
      if (!pointers.size) host.classList.remove('wb-mm-dragging');
    };
    const leave = () => {
      pointerInside = false;
      decorationDirty = true;
      host.classList.remove('wb-mm-pointer-inside');
      wake();
    };
    const focus = (event: FocusEvent) => {
      const element = (event.target as Element).closest<HTMLElement>('[data-mindmap-node]');
      const node = element && byKey.get(element.dataset.mindmapNode!);
      if (!node) return;
      setActive(node.key);
      // Pointer clicks and hover never move or release the following camera.
      if (tracking && host.dataset.inputMode !== 'keyboard') return;
      if (tracking) manual();
      const x = node.x * target.zoom + target.x,
        y = node.y * target.zoom + target.y;
      const padX = Math.min(bounds.width / 2, (node.width * target.zoom) / 2 + 40);
      const padY = Math.min(bounds.height / 2, (node.height * target.zoom) / 2 + 72);
      const limitX = Math.max(0, bounds.width / 2 - padX),
        limitY = Math.max(0, bounds.height / 2 - padY);
      setTarget({
        ...target,
        x: target.x + clamp(x, -limitX, limitX) - x,
        y: target.y + clamp(y, -limitY, limitY) - y
      });
    };
    const key = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if (!['Escape', '+', '=', '-', '−', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
      manual();
      const delta = event.shiftKey ? 120 : 64;
      if (event.key === 'Escape') {
        resetGesture();
        setActive(undefined);
        fit();
      } else if (event.key === '+' || event.key === '=') zoomAt(1.2, center());
      else if (event.key === '-' || event.key === '−') zoomAt(1 / 1.2, center());
      else if (event.key === 'ArrowLeft') setTarget({ ...target, x: target.x + delta }, true);
      else if (event.key === 'ArrowRight') setTarget({ ...target, x: target.x - delta }, true);
      else if (event.key === 'ArrowUp') setTarget({ ...target, y: target.y + delta }, true);
      else if (event.key === 'ArrowDown') setTarget({ ...target, y: target.y - delta }, true);
      else return;
      event.preventDefault();
    };
    type Gesture = Event & { scale: number; clientX: number; clientY: number };
    const gestureStart = (event: Event) => {
      event.preventDefault();
      if (touchPointers.size >= 2) return;
      if (tracking) {
        clearElastic(); returnMotion = undefined; target = { ...camera };
        elasticZoom = beginElasticZoom(center());
      }
      gestureActive = true;
      lastNativeGesture = Date.now();
      const scale = (event as Gesture).scale;
      gestureScale = Number.isFinite(scale) && scale > 0 ? scale : 1;
    };
    const gestureChange = (event: Event) => {
      event.preventDefault();
      if (!gestureActive || touchPointers.size >= 2) return;
      lastNativeGesture = Date.now();
      const value = event as Gesture;
      const point =
        Number.isFinite(value.clientX) && Number.isFinite(value.clientY)
          ? local(value.clientX, value.clientY)
          : center();
      const scale = value.scale;
      if (!Number.isFinite(scale) || scale <= 0) return;
      if (tracking && elasticZoom) {
        if (!elasticZoom.logScale) elasticZoom.point = point;
        elasticZoom.logScale += Math.log(scale / gestureScale);
        applyElasticZoom(elasticZoom);
      } else zoomAt(scale / gestureScale, point);
      gestureScale = scale;
    };
    const gestureEnd = (event: Event) => {
      event.preventDefault();
      if (!gestureActive) return;
      if (gestureActive) lastNativeGesture = Date.now();
      gestureActive = false;
      if (elasticZoom && tracking) { clearElastic(); track(true); }
    };
    const suspend = () => {
      if (disposed) return;
      resetGesture();
      leave();
      previousFrameTime = undefined;
      returnMotion = undefined;
      cameraVelocity = { x: 0, y: 0, zoom: 0 };
      lastDecoration = -Infinity;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      if (ambientTimer) window.clearTimeout(ambientTimer);
      ambientTimer = 0;
    };
    const visibility = () => {
      focusedRef.current = document.hasFocus();
      if (document.hidden || !focusedRef.current) suspend();
      else wake();
    };
    const blurWindow = () => {
      focusedRef.current = false;
      suspend();
    };
    const focusWindow = () => {
      focusedRef.current = true;
      wake();
    };
    const motionChange = () => {
      reduced = motion.matches;
      decorationDirty = true;
      viewDirty = true;
      host.dataset.reducedMotion = String(reduced);
      wake();
    };
    host.dataset.reducedMotion = String(reduced);
    const resize = new ResizeObserver(() => {
      if (disposed) return;
      const next = host.getBoundingClientRect();
      const changed = Math.abs(next.width - bounds.width) > .1 || Math.abs(next.height - bounds.height) > .1;
      bounds = next;
      if (!changed) return;
      viewDirty = true;
      decorationDirty = true;
      if (tracking && !interacting()) {
        if (returnMotion) { target = followTarget(); remember(); wake(); }
        else track();
      } else if (!interacting()) setTarget(target);
      else wake();
    });
    resize.observe(host);
    const intersection =
      typeof IntersectionObserver === 'undefined'
        ? undefined
        : new IntersectionObserver(([entry]) => {
            onScreen = entry.isIntersecting;
            if (!onScreen) suspend();
            else wake();
          });
    intersection?.observe(host);
    host.addEventListener('wheel', wheel, { passive: false });
    const keyboardMode = (event: KeyboardEvent) => {
      if (event.key === 'Tab' || host.contains(event.target as Node)) host.dataset.inputMode = 'keyboard';
    };
    document.addEventListener('keydown', keyboardMode, true);
    host.addEventListener('pointerdown', down);
    window.addEventListener('pointermove', move, { passive: false });
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    host.addEventListener('lostpointercapture', up);
    host.addEventListener('pointerleave', leave);
    host.addEventListener('focusin', focus);
    host.addEventListener('keydown', key);
    host.addEventListener('gesturestart', gestureStart, { passive: false });
    host.addEventListener('gesturechange', gestureChange, { passive: false });
    host.addEventListener('gestureend', gestureEnd, { passive: false });
    host.addEventListener('gesturecancel', gestureEnd, { passive: false });
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('blur', blurWindow);
    window.addEventListener('focus', focusWindow);
    motion.addEventListener('change', motionChange);
    wake();
    return () => {
      remember();
      interactionRef.current = {
        key: cameraKey, tracking, target: { ...target }, camera: { ...camera }, velocity: { ...cameraVelocity }, frameTime: previousFrameTime,
        returnMotion, pointerInside, pointer: { ...pointer }, lastPointer: { ...lastPointer },
        gestureScale, gestureActive, dragged, lastNativeGesture,
        touches: new Set(touchPointers), pointers: new Map(pointers), elastic, elasticZoom,
        wheelIntent, wheelBase, wheelKind, lastWheelTime, anchor, pinch
      };
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      if (ambientTimer) window.clearTimeout(ambientTimer);
      if (wheelTimer) window.clearTimeout(wheelTimer);
      for (const index of pulseIndices) hidePulse(index);
      controlsRef.current = undefined;
      resize.disconnect();
      intersection?.disconnect();
      host.removeEventListener('wheel', wheel);
      host.removeEventListener('pointerdown', down);
      document.removeEventListener('keydown', keyboardMode, true);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
      host.removeEventListener('lostpointercapture', up);
      host.removeEventListener('pointerleave', leave);
      host.removeEventListener('focusin', focus);
      host.removeEventListener('keydown', key);
      host.removeEventListener('gesturestart', gestureStart);
      host.removeEventListener('gesturechange', gestureChange);
      host.removeEventListener('gestureend', gestureEnd);
      host.removeEventListener('gesturecancel', gestureEnd);
      document.removeEventListener('visibilitychange', visibility);
      window.removeEventListener('blur', blurWindow);
      window.removeEventListener('focus', focusWindow);
      motion.removeEventListener('change', motionChange);
    };
  }, [cameraKey, graph, byKey, edges, follow, setActive]);

  const suppressClickCapture = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (Date.now() < suppressClickRef.current && !(event.target as Element).closest('[data-mm-controls]')) {
      event.preventDefault();
      event.stopPropagation();
    }
  };
  return { hostRef, worldRef, controlsRef, edges, suppressClickCapture, following };
}

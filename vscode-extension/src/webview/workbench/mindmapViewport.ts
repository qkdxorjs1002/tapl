import { useEffect, useMemo, useRef } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { constrainMindmapCamera, mindmapMinimumZoom } from './mindmapCamera';
import type { MindmapBounds, MindmapCamera } from './mindmapCamera';
import { mindmapConnectionGeometry, mindmapConnectionPoint } from './mindmapGeometry';
import type { MindmapRouting } from './mindmapGeometry';
import {
  MINDMAP_DECORATION_INTERVAL,
  mindmapConnectionBounds,
  mindmapIntersects,
  mindmapMagneticOffset,
  mindmapNearbyNodes,
  mindmapVisiblePulses,
  mindmapWorldView
} from './mindmapMotion';

/** Layout-only graph contract shared by RUN trees and associative memory DAGs. */
export type MindmapViewportGraph = {
  nodes: { key: string; x: number; y: number; width: number; height: number }[];
  edges: { from: string; to: string }[];
  bounds: MindmapBounds;
  routing?: MindmapRouting;
};
export type MindmapViewportControls = { fit: () => void; zoom: (factor: number) => void };
type Camera = MindmapCamera;
type Point = { x: number; y: number };
const cameras = new Map<string, Camera>();
const clamp = (n: number, min: number, max: number) => Math.max(min, Math.min(max, n));

/** Shared camera, gestures, focus visibility, and synchronized 2D edge motion. */
export function useMindmapViewport({
  graph,
  cameraKey,
  setActive
}: {
  graph: MindmapViewportGraph;
  cameraKey: string;
  setActive: (key?: string) => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<HTMLDivElement>(null);
  const controlsRef = useRef<MindmapViewportControls>();
  const suppressClickRef = useRef(0);
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
    let target: Camera = cameras.get(cameraKey) ? { ...cameras.get(cameraKey)! } : { x: 0, y: 0, zoom: 1 };
    target = constrainMindmapCamera(target, graph.bounds, bounds);
    let camera = { ...target };
    let raf = 0,
      ambientTimer = 0,
      disposed = false,
      onScreen = true,
      pointerInside = false;
    let pointer: Point = { x: bounds.width / 2, y: bounds.height / 2 };
    let lastPointer = { ...pointer };
    let gestureScale = 1,
      gestureActive = false,
      dragged = false,
      lastNativeGesture = 0;
    const touchPointers = new Set<number>();
    const pointers = new Map<number, Point>();
    let anchor: Point | undefined, pinch: { distance: number; center: Point } | undefined;
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let reduced = motion.matches;
    const nodeElements = Array.from(canvas.querySelectorAll<HTMLElement>('[data-mindmap-node]'));
    const pulses = Array.from(canvas.querySelectorAll<SVGCircleElement>('.wb-mm-pulse'));
    const paths = Array.from(canvas.querySelectorAll<SVGPathElement>('.wb-mm-edge'));
    // React can retain imperative styles across an effect restart; restore the current graph once.
    nodeElements.forEach((element, index) => {
      const node = graph.nodes[index];
      if (!node) return;
      const value = `translate(${node.x - node.width / 2}px, ${node.y - node.height / 2}px)`;
      if (element.style.transform !== value) element.style.transform = value;
    });
    paths.forEach((path, index) => {
      if (edges[index] && path.getAttribute('d') !== edges[index].path) path.setAttribute('d', edges[index].path);
    });
    const pointerLight = host.querySelector<HTMLElement>('.wb-mm-pointer-light');
    pointerLight?.style.setProperty('--mm-px', `${lastPointer.x}px`);
    pointerLight?.style.setProperty('--mm-py', `${lastPointer.y}px`);
    const nodeIndices = new Map(graph.nodes.map((node, index) => [node.key, index]));
    const nearbyNodes = mindmapNearbyNodes(graph.nodes);
    const connections = edges.map((edge) => ({ ...edge }));
    const edgeBounds = edges.map(mindmapConnectionBounds);
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
    const visible = () => !disposed && onScreen && !document.hidden;
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
      const easing = reduced || pointers.size ? 1 : 0.18;
      camera.x += (target.x - camera.x) * easing;
      camera.y += (target.y - camera.y) * easing;
      camera.zoom += (target.zoom - camera.zoom) * easing;
      if (Math.abs(target.x - camera.x) < 0.05) camera.x = target.x;
      if (Math.abs(target.y - camera.y) < 0.05) camera.y = target.y;
      if (Math.abs(target.zoom - camera.zoom) < 0.0001) camera.zoom = target.zoom;
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
      const cameraMoving = camera.x !== target.x || camera.y !== target.y || camera.zoom !== target.zoom;
      const pointerMoving = lastPointer.x !== pointer.x || lastPointer.y !== pointer.y;
      // Camera and pointer light keep their native frame rate; graph decorations have a separate budget.
      if (time - lastDecoration >= MINDMAP_DECORATION_INTERVAL || reduced) {
        const view = mindmapWorldView(camera, bounds, 12);
        if (viewDirty) {
          const nextPulses = reduced ? [] : mindmapVisiblePulses(edgeBounds, view);
          const selected = new Set(nextPulses);
          for (const index of pulseIndices) if (!selected.has(index) && pulses[index]) pulses[index].style.opacity = '0';
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
            connections[index] = { ...edge, ...connection };
            paths[index]?.setAttribute('d', connection.path);
          }
          decorationDirty = false;
        }
        for (const index of pulseIndices) {
          const pulse = pulses[index];
          if (!pulse || reduced) continue;
          const p = (time / 5200 + index * 0.173) % 1;
          const { x, y } = mindmapConnectionPoint(connections[index], p);
          pulse.setAttribute('cx', String(x));
          pulse.setAttribute('cy', String(y));
          pulse.style.opacity = String(Math.sin(p * Math.PI) * 0.65);
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
    const setTarget = (next: Camera) => {
      target = constrainMindmapCamera(next, graph.bounds, bounds);
      remember();
      wake();
    };
    const fit = () => {
      const zoom = clamp(Math.min((bounds.width - 72) / 1440, (bounds.height - 160) / 600), 0.72, 1);
      setTarget({ x: 0, y: 0, zoom });
    };
    const zoomAt = (factor: number, point: Point) => {
      const zoom = clamp(target.zoom * factor, mindmapMinimumZoom(graph.bounds, bounds), 2.8),
        ratio = zoom / target.zoom;
      setTarget({ x: point.x - (point.x - target.x) * ratio, y: point.y - (point.y - target.y) * ratio, zoom });
    };
    const local = (x: number, y: number) => ({
      x: x - bounds.left - bounds.width / 2,
      y: y - bounds.top - bounds.height / 2
    });
    const center = () => ({ x: 0, y: 0 });
    controlsRef.current = { fit, zoom: (factor) => zoomAt(factor, center()) };
    if (!cameras.has(cameraKey)) {
      fit();
      camera = { ...target };
    }
    transform();
    const wheel = (event: WheelEvent) => {
      if ((event.target as Element).closest('[data-mm-controls]')) return;
      event.preventDefault();
      if (gestureActive || Date.now() - lastNativeGesture < 140) return;
      const unit = event.deltaMode === 1 ? 18 : event.deltaMode === 2 ? bounds.height : 1;
      if (event.ctrlKey || event.metaKey)
        zoomAt(Math.exp(-event.deltaY * unit * 0.008), local(event.clientX, event.clientY));
      else {
        const horizontalFallback = event.shiftKey && event.deltaX === 0;
        setTarget({
          ...target,
          x: target.x - (horizontalFallback ? event.deltaY : event.deltaX) * unit,
          y: target.y - (horizontalFallback ? 0 : event.deltaY) * unit
        });
      }
    };
    const resetGesture = () => {
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
      if (event.button !== 0 || (event.target as Element).closest('[data-mm-controls]')) return;
      if (!pointers.size) {
        dragged = false;
        camera = { ...target };
      }
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      decorationDirty = true;
      wake();
      if (event.pointerType === 'touch') touchPointers.add(event.pointerId);
      rebase();
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
        zoomAt(current.distance / pinch.distance, local(pinch.center.x, pinch.center.y));
        setTarget({
          ...target,
          x: target.x + current.center.x - pinch.center.x,
          y: target.y + current.center.y - pinch.center.y
        });
        pinch = current;
      } else {
        const origin = !dragged && anchor ? anchor : previous;
        setTarget({ ...target, x: target.x + next.x - origin.x, y: target.y + next.y - origin.y });
      }
      dragged = true;
      suppressClickRef.current = Date.now() + 450;
      host.classList.add('wb-mm-dragging');
      event.preventDefault();
    };
    const up = (event: PointerEvent) => {
      if (!pointers.has(event.pointerId)) return;
      pointers.delete(event.pointerId);
      decorationDirty = true;
      wake();
      touchPointers.delete(event.pointerId);
      if (dragged) suppressClickRef.current = Date.now() + 450;
      rebase(); // Pinch → one-finger drag starts at the remaining finger, with no jump.
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
      const delta = event.shiftKey ? 120 : 64;
      if (event.key === 'Escape') {
        resetGesture();
        setActive(undefined);
        fit();
      } else if (event.key === '+' || event.key === '=') zoomAt(1.2, center());
      else if (event.key === '-' || event.key === '−') zoomAt(1 / 1.2, center());
      else if (event.key === 'ArrowLeft') setTarget({ ...target, x: target.x + delta });
      else if (event.key === 'ArrowRight') setTarget({ ...target, x: target.x - delta });
      else if (event.key === 'ArrowUp') setTarget({ ...target, y: target.y + delta });
      else if (event.key === 'ArrowDown') setTarget({ ...target, y: target.y - delta });
      else return;
      event.preventDefault();
    };
    type Gesture = Event & { scale: number; clientX: number; clientY: number };
    const gestureStart = (event: Event) => {
      event.preventDefault();
      if (touchPointers.size >= 2) return;
      gestureActive = true;
      lastNativeGesture = Date.now();
      gestureScale = (event as Gesture).scale || 1;
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
      const scale = value.scale || 1;
      zoomAt(scale / gestureScale, point);
      gestureScale = scale;
    };
    const gestureEnd = (event: Event) => {
      event.preventDefault();
      if (gestureActive) lastNativeGesture = Date.now();
      gestureActive = false;
    };
    const suspend = () => {
      resetGesture();
      leave();
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      if (ambientTimer) window.clearTimeout(ambientTimer);
      ambientTimer = 0;
    };
    const visibility = () => {
      if (document.hidden) suspend();
      else wake();
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
      bounds = host.getBoundingClientRect();
      viewDirty = true;
      decorationDirty = true;
      setTarget(target);
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
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('blur', suspend);
    motion.addEventListener('change', motionChange);
    wake();
    return () => {
      remember();
      disposed = true;
      suspend();
      for (const index of pulseIndices) if (pulses[index]) pulses[index].style.opacity = '0';
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
      document.removeEventListener('visibilitychange', visibility);
      window.removeEventListener('blur', suspend);
      motion.removeEventListener('change', motionChange);
    };
  }, [cameraKey, graph, byKey, edges, setActive]);

  const suppressClickCapture = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (Date.now() < suppressClickRef.current && !(event.target as Element).closest('[data-mm-controls]')) {
      event.preventDefault();
      event.stopPropagation();
    }
  };
  return { hostRef, worldRef, controlsRef, edges, suppressClickCapture };
}

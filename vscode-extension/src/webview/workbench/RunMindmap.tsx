import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { useI18n } from '../i18n';
import type { TaplItem, TaplRunSnapshot, TaplWorkflowRun } from '../types';
import { Icon } from './Icon';
import { buildRunMindmap, type MindmapNode } from './mindmap';
import { constrainMindmapCamera, mindmapMinimumZoom } from './mindmapCamera';
import './run-mindmap.css';

type Camera = { x: number; y: number; zoom: number };
type Point = { x: number; y: number };
const cameras = new Map<string, Camera>();
const clamp = (n: number, min: number, max: number) => Math.max(min, Math.min(max, n));
const openable = (item?: TaplItem) => typeof item?.id === 'number' && Number.isFinite(item.id);
const stateKind = (value?: string) =>
  value === 'In Progress' || value === 'active'
    ? 'progress'
    : value === 'Completed' || value === 'Finalized' || value === 'completed'
      ? 'completed'
      : value === 'Blocked' || value === 'blocked'
        ? 'blocked'
        : 'pending';

/** A RUN-owned camera survives record details and source-safe RUN navigation. */
export function RunMindmap({
  snapshot,
  open,
  back
}: {
  snapshot: TaplRunSnapshot;
  open: (item: TaplItem, run?: TaplWorkflowRun) => void;
  back?: () => void;
}): JSX.Element {
  const { t, status } = useI18n();
  const graph = useMemo(() => buildRunMindmap(snapshot), [snapshot]);
  const runKey = JSON.stringify([snapshot.run.source_db ?? '', snapshot.run.id]);
  const map = useRef<HTMLDivElement>(null);
  const world = useRef<HTMLDivElement>(null);
  const controls = useRef<{ fit: () => void; zoom: (factor: number) => void }>();
  const suppressClick = useRef(0);
  const [active, setActive] = useState<string>();
  const byKey = useMemo(() => new Map(graph.nodes.map((node) => [node.key, node])), [graph]);
  const related = useMemo(() => {
    if (!active || !byKey.has(active)) return undefined;
    const result = new Set([active]);
    let node = byKey.get(active);
    while (node?.parent) {
      result.add(node.parent);
      node = byKey.get(node.parent);
    }
    const descendants = (key: string) => {
      for (const edge of graph.edges)
        if (edge.from === key) {
          result.add(edge.to);
          descendants(edge.to);
        }
    };
    descendants(active);
    return result;
  }, [active, byKey, graph]);
  const edges = useMemo(
    () =>
      graph.edges.flatMap((edge, index) => {
        const from = byKey.get(edge.from),
          to = byKey.get(edge.to);
        if (!from || !to) return [];
        const direction = to.x >= from.x ? 1 : -1;
        const start = { x: from.x + (from.width / 2) * direction, y: from.y };
        const end = { x: to.x - (to.width / 2) * direction, y: to.y };
        const middle = (start.x + end.x) / 2;
        return [
          {
            ...edge,
            index,
            start,
            end,
            middle,
            path: `M ${start.x} ${start.y} C ${middle} ${start.y}, ${middle} ${end.y}, ${end.x} ${end.y}`
          }
        ];
      }),
    [graph, byKey]
  );

  useEffect(() => {
    const host = map.current,
      canvas = world.current;
    if (!host || !canvas) return;
    let bounds = host.getBoundingClientRect();
    let target: Camera = cameras.get(runKey) ? { ...cameras.get(runKey)! } : { x: 0, y: 0, zoom: 1 };
    target = constrainMindmapCamera(target, graph.bounds, bounds);
    let camera = { ...target };
    let raf = 0,
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
    const remember = () => {
      cameras.delete(runKey);
      cameras.set(runKey, { ...target });
      if (cameras.size > 24) cameras.delete(cameras.keys().next().value!);
    };
    const visible = () => !disposed && onScreen && !document.hidden;
    const transform = () => {
      canvas.style.transform = `translate(${camera.x}px, ${camera.y}px) scale(${camera.zoom})`;
      host.style.backgroundPosition = `${camera.x}px ${camera.y}px`;
      host.style.backgroundSize = `${26 * camera.zoom}px ${26 * camera.zoom}px`;
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
      transform();
      lastPointer.x += (pointer.x - lastPointer.x) * 0.16;
      lastPointer.y += (pointer.y - lastPointer.y) * 0.16;
      host.style.setProperty('--mm-px', `${lastPointer.x}px`);
      host.style.setProperty('--mm-py', `${lastPointer.y}px`);
      const offsets = new Map<string, Point>();
      nodeElements.forEach((element, index) => {
        const node = graph.nodes[index];
        if (!node) return;
        const dx = (lastPointer.x - bounds.width / 2 - camera.x) / camera.zoom - node.x;
        const dy = (lastPointer.y - bounds.height / 2 - camera.y) / camera.zoom - node.y;
        const influence = !reduced && pointerInside && !pointers.size ? Math.max(0, 1 - Math.hypot(dx, dy) / 280) : 0;
        const offset = { x: clamp(dx / 35, -3, 3) * influence, y: clamp(dy / 35, -3, 3) * influence };
        offsets.set(node.key, offset);
        element.style.transform = `translate(${node.x - node.width / 2 + offset.x}px, ${node.y - node.height / 2 + offset.y}px)`;
      });
      edges.forEach((edge, index) => {
        const from = offsets.get(edge.from) ?? { x: 0, y: 0 },
          to = offsets.get(edge.to) ?? { x: 0, y: 0 };
        const start = { x: edge.start.x + from.x, y: edge.start.y + from.y };
        const end = { x: edge.end.x + to.x, y: edge.end.y + to.y };
        const middle = (start.x + end.x) / 2;
        paths[index]?.setAttribute(
          'd',
          `M ${start.x} ${start.y} C ${middle} ${start.y}, ${middle} ${end.y}, ${end.x} ${end.y}`
        );
        const pulse = pulses[index];
        if (reduced || !pulse) return;
        const p = (time / 5200 + index * 0.173) % 1,
          q = 1 - p;
        const x = q * q * q * start.x + 3 * q * q * p * middle + 3 * q * p * p * middle + p * p * p * end.x;
        const y = q * q * q * start.y + 3 * q * q * p * start.y + 3 * q * p * p * end.y + p * p * p * end.y;
        pulse.setAttribute('cx', String(x));
        pulse.setAttribute('cy', String(y));
        pulse.style.opacity = String(Math.sin(p * Math.PI) * 0.65);
      });
      if (!reduced || camera.x !== target.x || camera.y !== target.y || camera.zoom !== target.zoom)
        raf = requestAnimationFrame(tick);
    };
    const wake = () => {
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
    controls.current = { fit, zoom: (factor) => zoomAt(factor, center()) };
    if (!cameras.has(runKey)) {
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
        pointerInside = true;
        host.classList.add('wb-mm-pointer-inside');
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
      suppressClick.current = Date.now() + 450;
      host.classList.add('wb-mm-dragging');
      event.preventDefault();
    };
    const up = (event: PointerEvent) => {
      if (!pointers.has(event.pointerId)) return;
      pointers.delete(event.pointerId);
      touchPointers.delete(event.pointerId);
      if (dragged) suppressClick.current = Date.now() + 450;
      rebase(); // Pinch → one-finger drag starts at the remaining finger, with no jump.
      if (!pointers.size) host.classList.remove('wb-mm-dragging');
    };
    const leave = () => {
      pointerInside = false;
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
    };
    const visibility = () => {
      if (document.hidden) suspend();
      else wake();
    };
    const motionChange = () => {
      reduced = motion.matches;
      host.dataset.reducedMotion = String(reduced);
      wake();
    };
    host.dataset.reducedMotion = String(reduced);
    const resize = new ResizeObserver(() => {
      bounds = host.getBoundingClientRect();
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
      controls.current = undefined;
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
  }, [runKey, graph, byKey, edges]);

  const nodeContent = (node: MindmapNode) => (
    <>
      <span className="wb-mm-meta">
        <span className="wb-mm-id">{node.kind === 'run' ? 'RUN' : node.item?.stable_id}</span>
        {node.status && (
          <span className="wb-mm-state" data-status={stateKind(node.status)}>
            <i />
            {status(node.status)}
          </span>
        )}
      </span>
      <span className="wb-mm-title" title={node.title}>
        {node.title || (node.kind === 'run' ? snapshot.run.slug || snapshot.run.id : '')}
      </span>
      {node.kind === 'run' && (
        <span className="wb-mm-run-foot">
          <span className="wb-mm-run-numbers">
            <span className="wb-mm-percent">
              {Math.round(graph.percent)}
              <small>%</small>
            </span>
            <span>
              {graph.completed} / {graph.total} {t('wbCompleted')}
            </span>
          </span>
          <svg className="wb-mm-ring" viewBox="0 0 48 48" aria-hidden="true">
            <circle className="wb-mm-ring-track" cx="24" cy="24" r="19" />
            <circle
              className="wb-mm-ring-value"
              cx="24"
              cy="24"
              r="19"
              pathLength="100"
              strokeDasharray={`${graph.percent} 100`}
            />
          </svg>
        </span>
      )}
      {node.kind === 'plan' && (
        <span className="wb-mm-plan-foot">
          <span>
            {node.completed} / {node.total} {t('wbCompleted')}
          </span>
          <span className="wb-mm-plan-track">
            <i style={{ width: `${node.total ? (node.completed / node.total) * 100 : 0}%` }} />
          </span>
        </span>
      )}
    </>
  );
  return (
    <div
      className="wb-run-mindmap"
      ref={map}
      role="region"
      tabIndex={0}
      aria-label={t('wbMindmap')}
      aria-description={t('wbMindmapHelp')}
      data-wb-page-heading
      data-run-key={runKey}
      onClickCapture={(event) => {
        if (Date.now() < suppressClick.current && !(event.target as Element).closest('[data-mm-controls]')) {
          event.preventDefault();
          event.stopPropagation();
        }
      }}
    >
      <div className="wb-mm-pointer-light" aria-hidden="true" />
      <div className="wb-mm-world" ref={world}>
        <svg className="wb-mm-connections" aria-hidden="true">
          {edges.map((edge) => (
            <g
              key={`${edge.from}:${edge.to}`}
              className={
                related ? (related.has(edge.from) && related.has(edge.to) ? 'wb-mm-edge-active' : 'wb-mm-edge-dim') : ''
              }
            >
              <path className="wb-mm-edge" d={edge.path} />
              <circle className="wb-mm-pulse" r="2" cx={edge.start.x} cy={edge.start.y} />
            </g>
          ))}
        </svg>
        {graph.nodes.map((node, index) => (
          <div
            className={`wb-mm-node${related ? (related.has(node.key) ? ' wb-mm-emphasis' : ' wb-mm-dim') : ''}`}
            key={node.key}
            data-kind={node.kind}
            data-mindmap-node={node.key}
            style={
              {
                width: node.width,
                height: node.height,
                transform: `translate(${node.x - node.width / 2}px, ${node.y - node.height / 2}px)`,
                '--mm-order': index
              } as CSSProperties
            }
            onPointerEnter={(event) => {
              if (event.pointerType !== 'touch') setActive(node.key);
            }}
            onPointerLeave={() => setActive(undefined)}
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) setActive(undefined);
            }}
          >
            {node.kind === 'run' ? (
              <div className="wb-mm-node-button" tabIndex={0}>
                {nodeContent(node)}
              </div>
            ) : (
              <button
                className="wb-mm-node-button"
                type="button"
                disabled={!openable(node.item)}
                title={!openable(node.item) ? t('wbRecordUnavailable') : undefined}
                data-wb-focus={`${node.kind}:${node.item?.id ?? node.key}`}
                data-status={node.status}
                onClick={() => {
                  if (openable(node.item)) open(node.item!, snapshot.run);
                }}
              >
                {nodeContent(node)}
              </button>
            )}
          </div>
        ))}
      </div>
      <div className="wb-mm-top-controls" data-mm-controls>
        {back && (
          <button
            className="wb-mm-icon-button wb-back"
            type="button"
            aria-label={t('wbBack')}
            data-wb-focus="back"
            onClick={back}
          >
            <Icon name="back" />
          </button>
        )}
      </div>
      <div className="wb-mm-legend" aria-label={t('status')}>
        {['In Progress', 'Completed', 'Blocked', 'Pending'].map((value) => (
          <span className="wb-mm-state" data-status={stateKind(value)} key={value}>
            <i />
            {status(value)}
          </span>
        ))}
      </div>
      <div className="wb-mm-camera-controls" data-mm-controls>
        <button
          className="wb-mm-icon-button"
          type="button"
          aria-label={t('wbMindmapZoomOut')}
          onClick={() => controls.current?.zoom(1 / 1.2)}
        >
          <svg className="wb-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 12h12" />
          </svg>
        </button>
        <button
          className="wb-mm-icon-button"
          type="button"
          aria-label={t('wbMindmapFit')}
          onClick={() => controls.current?.fit()}
        >
          <Icon name="focus" />
        </button>
        <button
          className="wb-mm-icon-button"
          type="button"
          aria-label={t('wbMindmapZoomIn')}
          onClick={() => controls.current?.zoom(1.2)}
        >
          <svg className="wb-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 12h12M12 6v12" />
          </svg>
        </button>
      </div>
    </div>
  );
}

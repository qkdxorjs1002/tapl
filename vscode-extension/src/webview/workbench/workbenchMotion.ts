import { useRef, useState, type RefObject } from 'react';
import { useBrowserLayoutEffect } from './effects';
import { viewIdentity, type WorkbenchRoute } from './model';

/** Search/filter results belong to the same page; details retain exact source and item identity. */
export function workbenchMotionIdentity(route: WorkbenchRoute): string {
  const view = route.view;
  const content = view && ['records', 'memories', 'search', 'error'].includes(view.type)
    ? view.type : view ? viewIdentity(view) : '';
  return JSON.stringify([route.runKey, route.page, content]);
}

export type WorkbenchMotion = 'page' | 'panel' | 'dialog' | 'scrim';
const durations: Record<WorkbenchMotion, number> = { page: 160, panel: 150, dialog: 160, scrim: 180 };

/** One cancellable animation, with no timers or lingering fill styles. */
export function animateWorkbench(
  element: HTMLElement,
  kind: WorkbenchMotion,
  entering: boolean,
  complete?: () => void
): () => void {
  const media = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : undefined;
  if (media?.matches || typeof element.animate !== 'function') {
    complete?.();
    return () => {};
  }
  const resting: Keyframe = { opacity: 1 };
  const displaced: Keyframe = { opacity: kind === 'page' ? 0.55 : 0 };
  // The page and scrim never transform: map camera measurements stay in the same coordinate space.
  if (kind === 'panel' || kind === 'dialog') {
    resting.transform = 'translateY(0)';
    displaced.transform = 'translateY(5px)';
  }
  const animation = element.animate(entering ? [displaced, resting] : [resting, displaced], {
    duration: durations[kind], easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'both'
  });
  let settled = false;
  const clean = () => {
    animation.removeEventListener('finish', finish);
    media?.removeEventListener('change', reduced);
    animation.cancel();
  };
  const finish = () => {
    if (settled) return;
    settled = true;
    clean();
    complete?.();
  };
  const reduced = () => { if (media?.matches) finish(); };
  animation.addEventListener('finish', finish, { once: true });
  media?.addEventListener('change', reduced);
  return () => { settled = true; clean(); };
}

/** Retain a closing surface only for its exit. Reopen cancels that exit before paint. */
export function useMotionPresence<T extends HTMLElement>(
  open: boolean, ref: RefObject<T>, kind: WorkbenchMotion, identity?: string
): boolean {
  const [retained, setRetained] = useState(open);
  const present = open || retained;
  useBrowserLayoutEffect(() => {
    const element = ref.current;
    if (!present || !element) return;
    element.inert = !open;
    if (open) setRetained(true);
    return animateWorkbench(element, kind, open, open ? undefined : () => setRetained(false));
  }, [open, present, kind, identity]);
  return present;
}

export function pageMotionReady(previous: string, next: string, ready: boolean): boolean {
  return ready && previous !== next;
}

export function usePageMotion(ref: RefObject<HTMLElement>, identity: string, ready = true): void {
  const previous = useRef(identity);
  useBrowserLayoutEffect(() => {
    if (!pageMotionReady(previous.current, identity, ready)) return;
    previous.current = identity;
    if (ref.current) return animateWorkbench(ref.current, 'page', true);
  }, [identity, ready]);
}

/** Modal lifetime follows presence, so native focus restoration happens after the exit. */
export function useDialogMotion(
  open: boolean, dialog: RefObject<HTMLDialogElement>, initialFocus: RefObject<HTMLElement>,
  fallbackFocus?: () => HTMLElement | null
): boolean {
  const present = useMotionPresence(open, dialog, 'dialog');
  const fallback = useRef(fallbackFocus);
  fallback.current = fallbackFocus;
  useBrowserLayoutEffect(() => {
    if (!present) return;
    const element = dialog.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    element?.showModal();
    initialFocus.current?.focus();
    return () => {
      element?.close();
      const target = opener?.isConnected && !opener.closest('[inert],[hidden]') ? opener : fallback.current?.();
      target?.focus({ preventScroll: true });
    };
  }, [present]);
  return present;
}

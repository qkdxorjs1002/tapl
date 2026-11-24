import { driver, type DriveStep, type PopoverDOM } from 'driver.js';
import 'driver.js/dist/driver.css';
import './tour.css';

export interface TourStep {
  id: string;
  title: string;
  description: string;
  target?: string;
  page?: 'current' | 'tasks' | 'records' | 'memories' | 'settings';
}

interface TourOptions {
  labels: { next: string; previous: string; done: string; close: string; progress: string };
  exampleLabel: string;
  prepare: (step: TourStep, signal: AbortSignal) => Promise<Element | undefined>;
  onEnd: (completed: boolean) => void;
}

// Driver uses innerHTML for popover text and most labels.
function escapeText(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function isVisible(element: Element): boolean {
  if (!element.isConnected) return false;
  const { width, height } = element.getBoundingClientRect();
  return width > 0 && height > 0 && (
    element.checkVisibility?.({ checkOpacity: true, checkVisibilityCSS: true })
    ?? getComputedStyle(element).visibility === 'visible'
  );
}

export function startDriverTour(steps: readonly TourStep[], { labels, exampleLabel, prepare, onEnd }: TourOptions): { destroy(): void } {
  const app = document.getElementById('root');
  const wasInert = app?.inert ?? false;
  const opener = document.activeElement;
  const listeners = new AbortController();
  let pending: AbortController | undefined;
  let popover: PopoverDOM | undefined;
  let ended = false;

  const driverSteps: (DriveStep & { popover: NonNullable<DriveStep['popover']> })[] = steps.map((step) => ({
    popover: {
      title: escapeText(step.title),
      description: escapeText(step.description),
      align: 'center'
    }
  }));
  const tour = driver({
    steps: driverSteps,
    animate: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    duration: 160,
    allowPageInteraction: false,
    allowScroll: false,
    disableActiveInteraction: true,
    overlayClickBehavior: 'none',
    overlayOpacity: 0.65,
    stagePadding: 5,
    stageRadius: 8,
    popoverOffset: 8,
    allowKeyboardControl: false,
    popoverClass: 'tapl-tour-popover',
    showProgress: true,
    progressText: escapeText(labels.progress),
    nextBtnText: escapeText(labels.next),
    prevBtnText: escapeText(labels.previous),
    doneBtnText: escapeText(labels.done),
    closeBtnLabel: labels.close,
    onNextClick: (_, __, { index }) => { if (index !== undefined) void showStep(index + 1); },
    onPrevClick: (_, __, { index }) => { if (index !== undefined) void showStep(index - 1); },
    onDoneClick: () => end(true),
    onCloseClick: () => end(false),
    onDestroyed: () => end(false),
    onElementMissing: (_, __, { index }) => { if (index !== undefined) void showStep(index); },
    onPopoverRender: (card, { index }) => {
      popover = card;
      card.wrapper.setAttribute('aria-modal', 'true');
      card.wrapper.tabIndex = -1;
      if (index !== undefined) card.wrapper.dataset.tourStep = steps[index].id;

      const content = document.createElement('div');
      content.className = 'tapl-tour-content';
      if (index !== undefined && steps[index].page) {
        const caption = document.createElement('div');
        caption.className = 'tapl-tour-example-label';
        caption.textContent = exampleLabel;
        content.append(caption);
      }
      content.append(card.title, card.description, card.footer);
      card.wrapper.append(content);
    }
  });

  function end(completed: boolean): void {
    if (ended) return;
    ended = true;
    pending?.abort();
    listeners.abort();
    tour.destroy();
    if (app) app.inert = wasInert;

    restoreFocus();
    onEnd(completed);
  }

  function restoreFocus(): void {
    const fallbacks = document.querySelectorAll<HTMLElement>('[data-tour-focus-return]');
    for (const candidate of [opener, ...fallbacks]) {
      if (!(candidate instanceof HTMLElement) || candidate === document.body || !isVisible(candidate)) continue;
      candidate.focus({ preventScroll: true });
      if (document.activeElement === candidate) return;
    }
    if (app && !app.inert) {
      const originalTabIndex = app.getAttribute('tabindex');
      app.tabIndex = -1;
      app.focus({ preventScroll: true });
      if (originalTabIndex === null) app.removeAttribute('tabindex');
      else app.setAttribute('tabindex', originalTabIndex);
    }
  }

  async function showStep(index: number): Promise<void> {
    const step = steps[index];
    if (ended || pending || !step) return;
    const request = new AbortController();
    pending = request;
    if (popover) {
      popover.wrapper.setAttribute('aria-busy', 'true');
      tour.updatePopover({ disableButtons: ['previous', 'next'] });
    }

    let target: Element | undefined;
    try {
      target = await prepare(step, request.signal);
    } catch {
      // A page that cannot supply an anchor still has a centered tour step.
    }
    if (request.signal.aborted) return;
    pending = undefined;

    const anchor = target && isVisible(target) ? target : undefined;
    driverSteps[index].element = anchor;
    tour.drive(index);
  }

  function trapKeys(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopImmediatePropagation();
      end(false);
      return;
    }
    if (event.key !== 'Tab') return;

    event.preventDefault();
    event.stopImmediatePropagation();
    if (!popover || !isVisible(popover.wrapper)) return;
    const buttons = [popover.closeButton, popover.previousButton, popover.nextButton]
      .filter((button) => !button.disabled && isVisible(button));
    const index = buttons.findIndex((button) => button === document.activeElement);
    const nextIndex = event.shiftKey
      ? (index > 0 ? index - 1 : buttons.length - 1)
      : (index + 1) % buttons.length;
    (buttons[nextIndex] ?? popover.wrapper).focus();
  }

  function keepFocus(event: FocusEvent): void {
    if (popover && isVisible(popover.wrapper) && !event.composedPath().includes(popover.wrapper)) {
      popover.wrapper.focus({ preventScroll: true });
    }
  }

  function blockOutsideInteraction(event: Event): void {
    if (popover && event.composedPath().includes(popover.wrapper)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }

  if (steps.length) {
    if (app) app.inert = true;
    const capture = { capture: true, signal: listeners.signal };
    window.addEventListener('keydown', trapKeys, capture);
    window.addEventListener('focusin', keepFocus, capture);
    for (const event of ['pointerdown', 'click', 'auxclick', 'contextmenu']) {
      window.addEventListener(event, blockOutsideInteraction, capture);
    }
    void showStep(0);
  } else {
    queueMicrotask(() => end(false));
  }

  return { destroy: () => end(false) };
}

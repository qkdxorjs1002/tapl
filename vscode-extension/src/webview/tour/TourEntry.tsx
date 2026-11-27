import { useEffect, useRef, useState } from 'react';
import type { SupportedLocale } from '../../i18n';
import type { TourHistory } from '../../viewer/tourHistory';
import { Icon } from '../workbench/Icon';
import { installedViewerRelease } from '../viewerRelease';
import { guideSteps, releaseSteps, tourCopy, tourOffer, type TourContext, type TourKind } from './content';
import { startDriverTour, type TourStep } from './driver';
import './entry.css';

export interface TourEntryState {
  history?: TourHistory;
  ready: boolean;
  helpRequested: boolean;
  consumeHelpRequest: () => void;
  save: (patch: TourHistory) => void;
  snoozed: boolean;
  snooze: () => void;
}

interface TourEntryProps {
  state: TourEntryState;
  context: TourContext;
  ctlAssets: boolean;
  locale: SupportedLocale;
  blockedByDialog: boolean;
  canInvite: boolean;
  selectPage: (page: NonNullable<TourStep['page']>) => void;
  showPreview: (step?: TourStep) => void;
  closeNavigation: () => void;
}

function findAnchor(shell: HTMLElement, target: string): Element | undefined {
  const scope = shell.querySelector(target === 'run-tabs' || target === 'theme' ? '.wb-topbar' : '[data-tour-preview-content]');
  return Array.from(scope?.querySelectorAll(`[data-tapl-tour="${target}"]`) ?? []).find(element => {
    if (!(element.checkVisibility?.({ checkOpacity: true, checkVisibilityCSS: true })
      ?? getComputedStyle(element).visibility === 'visible')) return false;
    const box = element.getBoundingClientRect();
    if (box.width < 8 || box.height < 8 || box.top < 0 || box.left < 0 ||
        box.right > document.documentElement.clientWidth || box.bottom > document.documentElement.clientHeight) return false;
    const page = element.closest('.wb-page-scroll');
    if (!page) return true;
    const bounds = page.getBoundingClientRect();
    return box.top >= bounds.top - 1 && box.bottom <= bounds.bottom + 1;
  });
}

function waitForAnchor(shell: HTMLElement, step: TourStep, signal: AbortSignal): Promise<Element | undefined> {
  if (!step.target) return Promise.resolve(undefined);
  const target = step.target;
  return new Promise(resolve => {
    let frame = 0;
    let scrolled = false;
    const onPreview = () => !step.page || shell.dataset.tourPreview === step.id;
    const timeout = window.setTimeout(() => finish(onPreview() ? findAnchor(shell, target) : undefined), 1500);
    const cancel = () => finish();
    function finish(anchor?: Element) {
      window.clearTimeout(timeout);
      window.cancelAnimationFrame(frame);
      signal.removeEventListener('abort', cancel);
      resolve(anchor);
    }
    function locate() {
      if (signal.aborted || !shell.isConnected) { finish(); return; }
      const onPage = onPreview();
      const anchor = onPage ? findAnchor(shell, target) : undefined;
      if (anchor) { finish(anchor); return; }
      if (onPage && target === 'display-settings' && !scrolled) {
        const viewerSettings = shell.querySelector('[data-tour-preview-content] [data-tapl-tour="display-settings"]');
        if (viewerSettings) {
          viewerSettings.scrollIntoView({ block: 'center' });
          scrolled = true;
        }
      }
      frame = window.requestAnimationFrame(locate);
    }
    signal.addEventListener('abort', cancel, { once: true });
    frame = window.requestAnimationFrame(locate);
  });
}

export function TourEntry({ state, context, ctlAssets, locale, blockedByDialog, canInvite, selectPage, showPreview, closeNavigation }: TourEntryProps): JSX.Element {
  const copy = tourCopy[locale];
  const helpButton = useRef<HTMLButtonElement>(null);
  const helpPanel = useRef<HTMLElement>(null);
  const notice = useRef<HTMLElement>(null);
  const activeTour = useRef<ReturnType<typeof startDriverTour>>();
  const [helpOpen, setHelpOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [finished, setFinished] = useState(false);
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || document.visibilityState === 'visible');
  const { history, ready, save, helpRequested, consumeHelpRequest, snoozed, snooze } = state;
  const { version: installedVersion } = installedViewerRelease(ctlAssets);
  const recent = releaseSteps(installedVersion, context, locale);
  const updates = history?.releaseSeenThrough
    ? releaseSteps(installedVersion, context, locale, history.releaseSeenThrough)
    : { steps: [] };
  const offer = history ? tourOffer(history, installedVersion, updates.steps.length > 0) : undefined;
  const canOffer = ready && visible && context.connected && !blockedByDialog;
  const showOffer = canOffer && canInvite && !snoozed && !helpOpen && !running ? offer?.kind : undefined;

  useEffect(() => {
    const update = () => setVisible(document.visibilityState === 'visible');
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  useEffect(() => {
    if (canOffer && offer?.advanceBaseline) save({ releaseSeenThrough: installedVersion });
  }, [canOffer, offer?.advanceBaseline, installedVersion, save]);

  useEffect(() => {
    if (!helpRequested || !ready || !visible || blockedByDialog || running) return;
    if (document.querySelector('dialog[open]')) return;
    closeNavigation();
    setHelpOpen(true);
    consumeHelpRequest();
  }, [helpRequested, ready, visible, blockedByDialog, running, consumeHelpRequest, closeNavigation]);

  useEffect(() => {
    if (!helpOpen) return;
    helpPanel.current?.querySelector('button')?.focus({ preventScroll: true });
    const outside = (event: PointerEvent) => {
      const path = event.composedPath();
      if (!(helpPanel.current && path.includes(helpPanel.current)) &&
          !(helpButton.current && path.includes(helpButton.current))) setHelpOpen(false);
    };
    document.addEventListener('pointerdown', outside, true);
    return () => document.removeEventListener('pointerdown', outside, true);
  }, [helpOpen]);

  useEffect(() => {
    if (!showOffer && !finished) return;
    const outside = (event: PointerEvent) => {
      if (!notice.current || event.composedPath().includes(notice.current)) return;
      if (showOffer) snooze();
      if (finished) setFinished(false);
    };
    document.addEventListener('pointerdown', outside, true);
    return () => document.removeEventListener('pointerdown', outside, true);
  }, [showOffer, finished, snooze]);

  useEffect(() => () => {
    const tour = activeTour.current;
    activeTour.current = undefined;
    tour?.destroy();
  }, []);

  const dismiss = (kind: TourKind, remember: boolean) => {
    snooze();
    if (!remember) return;
    if (kind === 'quick') save({ intro: 'dismissed' });
    if (kind === 'release') save({ releaseSeenThrough: installedVersion });
  };
  const start = (kind: TourKind) => {
    const shell = helpButton.current?.closest<HTMLElement>('.tapl-workbench');
    if (!shell || activeTour.current || document.querySelector('dialog[open]')) return;
    const pendingUpdate = offer?.kind === 'release';
    const steps = kind === 'release' ? (pendingUpdate ? updates.steps : recent.steps) : guideSteps(kind, context, locale);
    if (!steps.length) return;
    helpButton.current?.focus({ preventScroll: true });
    setHelpOpen(false);
    setFinished(false);
    snooze();
    setRunning(true);
    activeTour.current = startDriverTour(steps, {
      labels: copy.labels,
      exampleLabel: copy.example,
      prepare(step, signal) {
        showPreview(step.page ? step : undefined);
        return waitForAnchor(shell, step, signal);
      },
      onEnd(completed) {
        if (!activeTour.current) return;
        activeTour.current = undefined;
        showPreview();
        setRunning(false);
        if (!completed) return;
        if (kind === 'release' && pendingUpdate) {
          save({ releaseSeenThrough: installedVersion });
        } else if (kind === 'quick' && context.connected) {
          save({ intro: 'completed' });
          setFinished(true);
        }
      }
    });
  };
  const closeHelp = () => {
    setHelpOpen(false);
    helpButton.current?.focus({ preventScroll: true });
  };

  return <>
    <button ref={helpButton} type="button" className="btn btn-ghost btn-sm btn-square"
      aria-label={copy.help} title={copy.help} aria-expanded={helpOpen} aria-controls="tapl-tour-help"
      data-tour-focus-return data-wb-focus="tour-help" onClick={() => { closeNavigation(); setHelpOpen(!helpOpen); }}>
      <Icon name="help" />
    </button>
    {helpOpen && <section className="tapl-tour-entry tapl-tour-help" id="tapl-tour-help" ref={helpPanel} aria-labelledby="tapl-tour-help-title"
      onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); closeHelp(); } }}>
      <h2 id="tapl-tour-help-title">{copy.help}</h2>
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => start('quick')}>{copy.quick}</button>
      {!!recent.steps.length && context.connected && <button type="button" className="btn btn-ghost btn-sm"
        onClick={() => start('release')}>{copy.latest}<span className="tapl-tour-release-version">v{recent.version}</span></button>}
      {context.connected && (['blocked', 'references', 'appearance'] as const).map(guide =>
        <button type="button" className="btn btn-ghost btn-sm" key={guide} onClick={() => start(guide)}>{copy[guide]}</button>)}
    </section>}
    {showOffer && <section ref={notice} className="tapl-tour-entry tapl-tour-card" aria-labelledby="tapl-tour-card-title">
      <h2 id="tapl-tour-card-title">{showOffer === 'release' ? `${copy.latest} · v${installedVersion}` : copy.welcome}</h2>
      <p>{showOffer === 'release' ? copy.update : copy.intro}</p>
      <div className="tapl-tour-actions">
        <button type="button" className="btn btn-primary btn-sm" onClick={() => start(showOffer)}>
          {showOffer === 'release' ? copy.version : copy.quick}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { dismiss(showOffer, false); closeHelp(); }}>{copy.later}</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { dismiss(showOffer, true); closeHelp(); }}>{copy.dismiss}</button>
      </div>
    </section>}
    {finished && !helpOpen && !running && <section ref={notice} className="tapl-tour-entry tapl-tour-card" aria-labelledby="tapl-tour-card-title">
      <div className="tapl-tour-card-heading">
        <h2 id="tapl-tour-card-title">{copy.finished}</h2>
        <button type="button" className="btn btn-ghost btn-xs btn-square" aria-label={copy.labels.close}
          onClick={() => { setFinished(false); closeHelp(); }}><Icon name="close" /></button>
      </div>
      <div className="tapl-tour-actions">
        {(['current', 'records'] as const).map(page => <button type="button" className="btn btn-ghost btn-sm"
          key={page} onClick={() => { setFinished(false); selectPage(page); }}>{copy[page]}</button>)}
      </div>
    </section>}
  </>;
}

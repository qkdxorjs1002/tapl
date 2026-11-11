import { useEffect, useRef, useState, type RefObject } from 'react';
import { useBrowserLayoutEffect } from './effects';
import { useMotionPresence } from './workbenchMotion';
import { createPortal } from 'react-dom';
import { useI18n } from '../i18n';
import type { TaplItem, TaplRunSnapshot } from '../types';
import { Icon } from './Icon';
import { ItemCount, NavCount, StatusMark } from './components';
import { runKey, type RunPageState } from './model';
import type { OpenItem } from './RunViews';

type Kind = 'PLAN' | 'TASK' | 'FINDING';
type Mode = 'pointer' | 'keyboard' | 'touch';
export function Explore({
  snapshot,
  enabled,
  mobile,
  sidebarRef,
  menuRef,
  prefs,
  update,
  openItem,
  navigationKey,
  onActiveChange
}: {
  snapshot?: TaplRunSnapshot;
  enabled: boolean;
  mobile: boolean;
  sidebarRef: RefObject<HTMLElement>;
  menuRef: RefObject<HTMLButtonElement>;
  prefs: RunPageState;
  update: (patch: Partial<RunPageState>, key?: string) => void;
  openItem: OpenItem;
  navigationKey: string;
  onActiveChange?: (active: boolean) => void;
}): JSX.Element {
  const { t } = useI18n();
  const [kind, setKind] = useState<Kind | null>(null);
  useEffect(() => {
    onActiveChange?.(!!kind);
    return () => onActiveChange?.(false);
  }, [kind, onActiveChange]);
  const panel = useRef<HTMLElement>(null);
  const lastKind = useRef<Kind>('PLAN');
  if (kind) lastKind.current = kind;
  const shownKind = kind ?? lastKind.current;
  const present = useMotionPresence(!!kind, panel, 'panel', kind ?? undefined);
  const triggers = useRef<Partial<Record<Kind, HTMLButtonElement | null>>>({});
  const kindRef = useRef<Kind | null>(null);
  const mode = useRef<Mode>('pointer');
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const suppress = useRef<Kind | null>(null);
  const focusNext = useRef(false);
  const enabledRef = useRef(enabled);
  const owner = useRef({
    key: runKey(snapshot?.run),
    scrolls: prefs.exploreScrolls
  });
  enabledRef.current = enabled;
  const itemsFor = (value: Kind): TaplItem[] =>
    value === 'PLAN'
      ? (snapshot?.plans ?? [])
      : value === 'TASK'
        ? (snapshot?.tasks ?? [])
        : (snapshot?.findings ?? []);
  const clearClose = () => {
    if (timer.current) clearTimeout(timer.current);
  };
  const captureScroll = () => {
    const current = kindRef.current;
    const list = panel.current?.querySelector<HTMLElement>('.wb-fold-list');
    if (current && list) {
      owner.current.scrolls = {
        ...owner.current.scrolls,
        [current]: list.scrollTop
      };
      update({ exploreScrolls: owner.current.scrolls }, owner.current.key);
    }
  };
  const close = (returnFocus = false, responsive = false) => {
    clearClose();
    const previous = kindRef.current;
    const hadFocus = panel.current?.contains(document.activeElement);
    captureScroll();
    kindRef.current = null;
    if (panel.current) {
      panel.current.inert = true;
    }
    setKind(null);
    if (returnFocus) suppress.current = previous;
    if (returnFocus || (responsive && hadFocus)) {
      const trigger = responsive || !enabledRef.current ? menuRef.current : previous && triggers.current[previous];
      trigger?.focus({ preventScroll: true });
    }
  };
  const open = (next: Kind, inputMode: Mode, focus = false) => {
    if (!enabledRef.current) return;
    clearClose();
    if (mode.current === 'keyboard' && panel.current?.contains(document.activeElement) && inputMode === 'pointer')
      return;
    suppress.current = null;
    if (kindRef.current !== next) captureScroll();
    owner.current = {
      key: runKey(snapshot?.run),
      scrolls: prefs.exploreScrolls
    };
    mode.current = inputMode;
    kindRef.current = next;
    focusNext.current = focus;
    setKind(next);
    if (focus && kind === next)
      queueMicrotask(() =>
        panel.current
          ?.querySelector<HTMLElement>('.wb-fold-list button, .wb-explore-close')
          ?.focus({ preventScroll: true })
      );
  };
  const position = () => {
    const current = kindRef.current;
    const box = panel.current;
    const side = sidebarRef.current;
    const trigger = current && triggers.current[current];
    if (!current || !box || !side || !trigger) return;
    const sidebar = side.getBoundingClientRect(),
      anchor = trigger.getBoundingClientRect();
    const edge = mobile
      ? sidebar.right
      : sidebar.left + (parseFloat(getComputedStyle(side).getPropertyValue('--wb-expanded-rail')) || 256);
    if (!enabledRef.current || side.inert || anchor.bottom <= sidebar.top || anchor.top >= sidebar.bottom) {
      close(false, true);
      return;
    }
    const width = Math.min(336, window.innerWidth - 24);
    box.style.width = `${width}px`;
    box.style.left = `${edge + width + 8 <= window.innerWidth - 12 ? edge + 8 : 12}px`;
    box.style.top = `${Math.max(sidebar.top + 8, Math.min(anchor.top, window.innerHeight - box.offsetHeight - 12))}px`;
  };
  const scheduleClose = () => {
    clearClose();
    if (mode.current !== 'pointer') return;
    timer.current = setTimeout(() => {
      const current = kindRef.current;
      if (!current || panel.current?.contains(document.activeElement)) return;
      if (!triggers.current[current]?.matches(':hover') && !panel.current?.matches(':hover')) close();
    }, 440);
  };
  useBrowserLayoutEffect(() => {
    if (!enabled) close(false, true);
  }, [enabled]);
  useBrowserLayoutEffect(() => {
    close();
  }, [navigationKey]);
  useBrowserLayoutEffect(() => {
    if (!kind || !panel.current) return;
    panel.current.hidden = false;
    panel.current.inert = false;
    const list = panel.current.querySelector<HTMLElement>('.wb-fold-list');
    if (list) list.scrollTop = prefs.exploreScrolls[kind] ?? 0;
    position();
    if (focusNext.current) {
      panel.current
        .querySelector<HTMLElement>('.wb-fold-list button, .wb-explore-close')
        ?.focus({ preventScroll: true });
      focusNext.current = false;
    }
  }, [kind]);
  useEffect(() => {
    if (!kind) return;
    const outside = (event: PointerEvent) => {
      if (
        !panel.current?.contains(event.target as Node) &&
        !Object.values(triggers.current).some((trigger) => trigger?.contains(event.target as Node))
      )
        close();
    };
    const focusOutside = (event: FocusEvent) => {
      if (
        mode.current === 'keyboard' &&
        !panel.current?.contains(event.target as Node) &&
        !Object.values(triggers.current).some((trigger) => trigger?.contains(event.target as Node))
      )
        close();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        close(true);
      }
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('focusin', focusOutside);
    document.addEventListener('keydown', escape, true);
    window.addEventListener('resize', position);
    const resize = new ResizeObserver(position);
    if (sidebarRef.current) resize.observe(sidebarRef.current);
    sidebarRef.current?.addEventListener('scroll', position);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('focusin', focusOutside);
      document.removeEventListener('keydown', escape, true);
      window.removeEventListener('resize', position);
      resize.disconnect();
      sidebarRef.current?.removeEventListener('scroll', position);
    };
  }, [kind]);
  useEffect(() => () => clearClose(), []);
  return (
    <>
      <div className="wb-record-folds">
        {(['PLAN', 'TASK', 'FINDING'] as const).map((value) => (
          <button
            type="button"
            className="wb-fold-trigger"
            aria-label={`${value} · ${t(itemsFor(value).length === 1 ? 'wbItem' : 'wbItems', { count: itemsFor(value).length })}`}
            data-wb-tooltip="true"
            key={value}
            ref={(element) => {
              triggers.current[value] = element;
            }}
            aria-expanded={kind === value}
            aria-controls="wb-explore-panel"
            aria-haspopup="dialog"
            data-wb-focus={`explore:${value}`}
            onPointerEnter={(event) => {
              if (event.pointerType === 'mouse' && !mobile && suppress.current !== value) open(value, 'pointer');
            }}
            onPointerLeave={() => {
              if (suppress.current === value) suppress.current = null;
              scheduleClose();
            }}
            onClick={(event) => {
              const inputMode: Mode =
                event.detail === 0 ? 'keyboard' : matchMedia('(hover: none)').matches || mobile ? 'touch' : 'pointer';
              if (kindRef.current === value && mode.current === inputMode && inputMode !== 'pointer') close(true);
              else open(value, inputMode, inputMode === 'keyboard');
            }}
            onKeyDown={(event) => {
              if (
                ['ArrowRight', 'ArrowDown'].includes(event.key) ||
                (event.key === 'Tab' && !event.shiftKey && kind === value)
              ) {
                event.preventDefault();
                open(value, 'keyboard', true);
              }
            }}
          >
            <Icon name={value.toLowerCase()} />
            <span className="wb-nav-label" aria-hidden="true">
              {value}
            </span>
            <NavCount className="wb-fold-count" count={itemsFor(value).length} />
            <Icon name="chevron" />
          </button>
        ))}
      </div>
      {present &&
        createPortal(
          <section
            ref={panel}
            id="wb-explore-panel"
            className="wb-explore-panel"
            data-wb-motion="presence"
            aria-hidden={!kind}
            role="dialog"
            aria-modal="false"
            aria-labelledby="wb-explore-title"
            onPointerEnter={clearClose}
            onPointerLeave={scheduleClose}
            onKeyDown={(event) => {
              mode.current = 'keyboard';
              if (event.key === 'ArrowLeft') {
                event.preventDefault();
                close(true);
              }
              const buttons = [
                ...event.currentTarget.querySelectorAll<HTMLButtonElement>('.wb-fold-list button:not(:disabled)')
              ];
              const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
              if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) && buttons.length) {
                event.preventDefault();
                const next =
                  event.key === 'Home'
                    ? 0
                    : event.key === 'End'
                      ? buttons.length - 1
                      : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
                buttons[next].focus();
              }
            }}
          >
            <header>
              <h2 id="wb-explore-title">
                <Icon name={shownKind.toLowerCase()} />
                {shownKind}
              </h2>
              <span>
                <ItemCount count={itemsFor(shownKind).length} />
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm btn-square wb-explore-close"
                aria-label={t('wbClose')}
                onClick={() => close(true)}
              >
                <Icon name="close" />
              </button>
            </header>
            <div className="wb-fold-list" aria-labelledby="wb-explore-title">
              {itemsFor(shownKind).map((item) => (
                <button
                  key={item.id ?? item.stable_id}
                  type="button"
                  disabled={item.id == null}
                  onClick={() => {
                    close(true);
                    openItem(item, snapshot?.run);
                  }}
                >
                  <span className="wb-record-code">
                    <StatusMark value={item.status} dotOnly />
                    {item.stable_id}
                  </span>
                  <span>{item.title}</span>
                </button>
              ))}
              {!itemsFor(shownKind).length && <p className="wb-fold-empty">{t('wbNoRecords')}</p>}
            </div>
          </section>,
          document.body
        )}
    </>
  );
}

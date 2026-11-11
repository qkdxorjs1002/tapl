import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react';
import { useBrowserLayoutEffect } from './effects';
import { useI18n } from '../i18n';
import type { TaplItem } from '../types';
import { formatExecutionTiming, isRunningExecutionTiming } from '../executionTiming';
import { useState } from 'react';
import { Icon } from './Icon';

export function StatusMark({ value, dotOnly = false }: { value?: string; dotOnly?: boolean }): JSX.Element | null {
  const { status } = useI18n();
  if (!value) return null;
  return (
    <span className="wb-status-label" data-status={value}>
      <span className="wb-status-dot" aria-hidden="true" />
      <span className={dotOnly ? 'wb-sr-only' : undefined}>{status(value)}</span>
    </span>
  );
}
export function ItemCount({ count }: { count: number }): JSX.Element {
  const { t } = useI18n();
  return <>{t(count === 1 ? 'wbItem' : 'wbItems', { count })}</>;
}
/** Navigation counts are visible only while the rail is expanded. */
export function NavCount({
  count,
  percentage = false,
  className = ''
}: {
  count: number;
  percentage?: boolean;
  className?: string;
}): JSX.Element {
  return (
    <span className={`wb-rail-count ${className}`} data-wb-count={count} aria-hidden="true">
      <span className="wb-count-full">{percentage ? `${count}%` : <ItemCount count={count} />}</span>
    </span>
  );
}
export function EmptyState({
  title,
  help,
  children,
  icon = 'inbox'
}: {
  title: string;
  help?: string;
  children?: ReactNode;
  icon?: string;
}): JSX.Element {
  return (
    <section className="wb-empty">
      <Icon name={icon} />
      <h2>{title}</h2>
      {help && <p>{help}</p>}
      {children}
    </section>
  );
}
export function PageHeading({
  title,
  back,
  children
}: {
  title: string;
  back?: () => void;
  children?: ReactNode;
}): JSX.Element {
  const { t } = useI18n();
  return (
    <div className="wb-page-heading">
      <div>
        <h1 tabIndex={-1} data-wb-page-heading>
          {title}
        </h1>
        {children}
      </div>
      {back && (
        <button className="btn btn-sm wb-back" type="button" onClick={back} data-wb-focus="back">
          <Icon name="back" />
          {t('wbBack')}
        </button>
      )}
    </div>
  );
}
export function HorizontalTrack({
  name,
  label,
  children,
  className = ''
}: {
  name: string;
  label: string;
  children: ReactNode;
  className?: string;
}): JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  const updateEdges = () => {
    const track = ref.current;
    if (!track) return;
    const remaining = track.scrollWidth - track.clientWidth - track.scrollLeft;
    track.style.setProperty('--wb-track-left-opacity', String(Math.max(0, Math.min(1, 1 - track.scrollLeft / 28))));
    track.style.setProperty('--wb-track-right-opacity', String(Math.max(0, Math.min(1, 1 - remaining / 28))));
  };
  useBrowserLayoutEffect(updateEdges);
  useEffect(() => {
    if (!ref.current) return;
    const resize = new ResizeObserver(updateEdges);
    resize.observe(ref.current);
    return () => resize.disconnect();
  }, []);
  return (
    <div className="wb-scroll-viewport">
      <div
        ref={ref}
        className={`wb-horizontal-track ${className}`}
        data-wb-track={name}
        role="region"
        aria-label={label}
        tabIndex={0}
        onScroll={updateEdges}
        onFocus={(event) => {
          if (event.target !== event.currentTarget)
            (event.target as HTMLElement).scrollIntoView({
              block: 'nearest',
              inline: 'nearest'
            });
        }}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key))
            return;
          event.preventDefault();
          const track = event.currentTarget;
          const first = track.firstElementChild as HTMLElement | null;
          const step = (first?.getBoundingClientRect().width ?? 300) + 14;
          track.scrollTo({
            left:
              event.key === 'Home'
                ? 0
                : event.key === 'End'
                  ? track.scrollWidth
                  : track.scrollLeft + (event.key === 'ArrowRight' ? step : -step),
            behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
          });
        }}
      >
        {children}
      </div>
    </div>
  );
}
export function TaskDuration({ item }: { item: TaplItem }): JSX.Element | null {
  const { locale, t } = useI18n();
  const [now, setNow] = useState(Date.now);
  const running = isRunningExecutionTiming(item.execution_timing, item.status);
  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  const timing = formatExecutionTiming(item.execution_timing, item.status, locale, now);
  return timing ? (
    <span className="wb-duration" title={t(timing.running ? 'elapsedTime' : 'duration')}>
      {timing.duration}
    </span>
  ) : null;
}
export type TrackStyle = CSSProperties & {
  '--wb-track-left-opacity'?: number;
  '--wb-track-right-opacity'?: number;
};

import type { SupportedLocale } from '../i18n';
import type { TaplExecutionTiming } from './types';

export interface FormattedExecutionTiming {
  running: boolean;
  duration: string;
}

export function isRunningExecutionTiming(timing: TaplExecutionTiming | null | undefined, status?: string): boolean {
  return status === 'In Progress'
    && timing?.finished_at == null
    && typeof timing?.running_since === 'string'
    && Number.isFinite(Date.parse(timing.running_since))
    && Number.isFinite(Date.parse(timing.as_of));
}

export function formatExecutionTiming(
  timing: TaplExecutionTiming | null | undefined,
  status: string | undefined,
  locale: SupportedLocale,
  nowMs: number
): FormattedExecutionTiming | null {
  if (!timing || !Number.isFinite(timing.elapsed_seconds) || timing.elapsed_seconds < 0) {
    return null;
  }
  const running = isRunningExecutionTiming(timing, status);
  const snapshotMs = running ? Date.parse(timing.as_of) : nowMs;
  const extraSeconds = running ? Math.max(0, nowMs - snapshotMs) / 1000 : 0;
  const totalSeconds = Math.floor(timing.elapsed_seconds + extraSeconds);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor(totalSeconds % 86400 / 3600);
  const minutes = Math.floor(totalSeconds % 3600 / 60);
  const seconds = totalSeconds % 60;
  const units: Array<[number, string, string]> = [
    [days, 'd', '일'],
    [hours, 'h', '시간'],
    [minutes, 'm', '분'],
    [seconds, 's', '초']
  ];
  return {
    running,
    duration: units.filter(([value]) => value > 0).map(([value, en, ko]) => `${value}${locale === 'ko' ? ko : en}`).join(' ') || (locale === 'ko' ? '0초' : '0s')
  };
}

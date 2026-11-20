import type { TourHistory } from './types';

export type { TourHistory } from './types';
export const TOUR_HISTORY_KEY = 'tapl.viewer.product-tour.v1';

interface Version {
  core: bigint[];
  prerelease: string[];
  normalized: string;
}

function parseVersion(value: string): Version | undefined {
  if (value.length > 128) return;
  const match = /^(?:v)?((0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?)(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/.exec(value);
  if (!match || match[0] !== value) return;
  const prerelease = match[5]?.split('.') ?? [];
  if (prerelease.some(part => /^0\d+$/.test(part))) return;
  return { core: match.slice(2, 5).map(BigInt), prerelease, normalized: match[1] };
}

export function isStableTourVersion(version: string): boolean {
  return parseVersion(version)?.prerelease.length === 0;
}

export function compareTourVersions(a: string, b: string): number | undefined {
  const left = parseVersion(a), right = parseVersion(b);
  if (!left || !right) return undefined;
  for (let index = 0; index < left.core.length; index++) {
    if (left.core[index] !== right.core[index]) return left.core[index] < right.core[index] ? -1 : 1;
  }
  if (!left.prerelease.length || !right.prerelease.length) {
    return Math.sign(right.prerelease.length - left.prerelease.length);
  }
  for (let index = 0; index < Math.min(left.prerelease.length, right.prerelease.length); index++) {
    const lhs = left.prerelease[index], rhs = right.prerelease[index];
    if (lhs === rhs) continue;
    const leftNumeric = /^\d+$/.test(lhs), rightNumeric = /^\d+$/.test(rhs);
    if (leftNumeric !== rightNumeric) return leftNumeric ? -1 : 1;
    if (leftNumeric && lhs.length !== rhs.length) return lhs.length < rhs.length ? -1 : 1;
    return lhs < rhs ? -1 : 1;
  }
  return Math.sign(left.prerelease.length - right.prerelease.length);
}

export function normalizeTourHistory(value: unknown): TourHistory {
  const history: TourHistory = {};
  if (!value || typeof value !== 'object' || Array.isArray(value)) return history;
  const { intro, releaseSeenThrough } = value as Record<string, unknown>;
  if (intro === 'completed' || intro === 'dismissed') history.intro = intro;
  const release = typeof releaseSeenThrough === 'string' ? parseVersion(releaseSeenThrough) : undefined;
  if (release) history.releaseSeenThrough = release.normalized;
  return history;
}

export function mergeTourHistory(current: TourHistory, next: TourHistory): TourHistory {
  const left = normalizeTourHistory(current), right = normalizeTourHistory(next);
  const intro = left.intro === 'completed' || right.intro === 'completed' ? 'completed' : left.intro ?? right.intro;
  let releaseSeenThrough = left.releaseSeenThrough;
  if (right.releaseSeenThrough && (!releaseSeenThrough || compareTourVersions(right.releaseSeenThrough, releaseSeenThrough) === 1)) {
    releaseSeenThrough = right.releaseSeenThrough;
  }
  return { ...(intro ? { intro } : {}), ...(releaseSeenThrough ? { releaseSeenThrough } : {}) };
}

import { compareTourVersions, isStableTourVersion } from '../viewer/tourHistory';

export const RELEASE_API = 'https://api.github.com/repos/qkdxorjs1002/tapl/releases/latest';
const RELEASE_BASE = 'https://github.com/qkdxorjs1002/tapl/releases';
export const RELEASE_CACHE_KEY = 'tapl.viewer.latest-release.v1';
export const RELEASE_CACHE_MS = 60 * 60 * 1000;
export const RELEASE_RETRY_MS = 5 * 60 * 1000;

export interface ViewerRelease { tag: string; version: string }

export function isNewerRelease(candidate: string, current: string): boolean {
  // Only stable releases are advertised, even if a cached/API response is malformed.
  return isStableTourVersion(candidate) && compareTourVersions(candidate, current) === 1;
}

export function releaseUrl(tag: string): string {
  return compareTourVersions(tag, tag) === 0 ? `${RELEASE_BASE}/tag/${encodeURIComponent(tag)}` : RELEASE_BASE;
}

export function stableRelease(value: unknown): ViewerRelease | undefined {
  if (!value || typeof value !== 'object') return;
  const release = value as Record<string, unknown>;
  if (release.draft !== false || release.prerelease !== false || typeof release.tag_name !== 'string') return;
  if (!isStableTourVersion(release.tag_name)) return;
  return { tag: release.tag_name, version: release.tag_name.replace(/^v/, '') };
}

interface ReleaseCache { checkedAt: number; retryAt: number; release?: ViewerRelease }
interface CheckerOptions {
  fetch: typeof fetch;
  storage?: Pick<Storage, 'getItem' | 'setItem'>;
  now?: () => number;
  timeoutMs?: number;
}

// One checker per App lifetime; in-flight calls and workspace changes share the same request.
export function createReleaseChecker({ fetch: fetchRelease, storage, now = Date.now, timeoutMs = 6000 }: CheckerOptions) {
  let cache: ReleaseCache = { checkedAt: 0, retryAt: 0 };
  let pending: Promise<ViewerRelease | undefined> | undefined;
  try {
    const raw = storage?.getItem(RELEASE_CACHE_KEY);
    const stored = raw ? JSON.parse(raw) : undefined;
    const timestamp = now();
    if (stored && Number.isFinite(stored.checkedAt) && stored.checkedAt > 0 && stored.checkedAt <= timestamp &&
        Number.isFinite(stored.retryAt) && stored.retryAt <= timestamp + RELEASE_CACHE_MS) {
      const release = stableRelease({ tag_name: stored.release?.tag, draft: false, prerelease: false });
      cache = { checkedAt: stored.checkedAt, retryAt: stored.retryAt, release };
    }
  } catch { /* Storage can be unavailable in an embedded webview. */ }
  const save = () => {
    try { storage?.setItem(RELEASE_CACHE_KEY, JSON.stringify(cache)); } catch { /* Use the in-memory cache. */ }
  };
  return {
    cached: () => cache.release,
    check(): Promise<ViewerRelease | undefined> {
      if (pending) return pending;
      if (now() < cache.retryAt) return Promise.resolve(cache.release);
      pending = (async () => {
        const controller = new AbortController();
        let timer: ReturnType<typeof setTimeout> | undefined;
        try {
          // Race as well as abort: a stalled transport must not leave the checker in flight forever.
          const release = await Promise.race([
            (async () => {
              const response = await fetchRelease(RELEASE_API, { credentials: 'omit', referrerPolicy: 'no-referrer', signal: controller.signal,
                headers: { Accept: 'application/vnd.github+json' } });
              if (!response.ok) throw new Error('Release check failed');
              const value = stableRelease(await response.json());
              if (!value) throw new Error('Invalid release');
              return value;
            })(),
            new Promise<never>((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(new Error('Release check timed out')); }, timeoutMs); })
          ]);
          const checkedAt = now();
          cache = { checkedAt, retryAt: checkedAt + RELEASE_CACHE_MS, release };
        } catch {
          cache = { ...cache, checkedAt: now(), retryAt: now() + RELEASE_RETRY_MS };
        } finally {
          if (timer !== undefined) clearTimeout(timer);
          save();
        }
        return cache.release;
      })().finally(() => { pending = undefined; });
      return pending;
    }
  };
}

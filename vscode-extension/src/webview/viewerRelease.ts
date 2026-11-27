import { version as extensionVersion } from '../../package.json';
import { compareTourVersions, isStableTourVersion } from '../viewer/tourHistory';

export const VIEWER_RELEASES_API = 'https://api.github.com/repos/qkdxorjs1002/tapl/releases';
export const RELEASE_API = `${VIEWER_RELEASES_API}/latest`;
const RELEASE_BASE = 'https://github.com/qkdxorjs1002/tapl/releases';
const VIEWER_TAG_PREFIX = 'viewer-';
export const RELEASE_CACHE_KEY = 'tapl.viewer.latest-release.ctl.v1';
const VIEWER_RELEASE_CACHE_KEY = 'tapl.viewer.latest-release.viewer.v1';
export const RELEASE_CACHE_MS = 60 * 60 * 1000;
export const RELEASE_RETRY_MS = 5 * 60 * 1000;

type ReleaseChannel = 'ctl' | 'viewer';
export interface ViewerRelease { tag: string; version: string }

function versionFromTag(tag: string, channel: ReleaseChannel): string | undefined {
  if (channel === 'viewer' && !tag.startsWith(VIEWER_TAG_PREFIX)) return;
  const version = channel === 'viewer' ? tag.slice(VIEWER_TAG_PREFIX.length) : tag;
  if (channel === 'viewer' && version.startsWith('v')) return;
  if (compareTourVersions(version, version) === 0) return version.replace(/^v/, '');
}

export function installedViewerRelease(browser: boolean): ViewerRelease {
  if (!browser) return { tag: `${VIEWER_TAG_PREFIX}${extensionVersion}`, version: extensionVersion };
  const tag = typeof __TAPL_CTL_RELEASE_TAG__ === 'string' ? __TAPL_CTL_RELEASE_TAG__ : '';
  const version = versionFromTag(tag, 'ctl');
  // Source builds can use the manifest version when no ctl release tag is provided.
  return version ? { tag, version } : { tag: extensionVersion, version: extensionVersion };
}

export function isNewerRelease(candidate: string, current: string): boolean {
  // Only stable releases are advertised, even if a cached/API response is malformed.
  return isStableTourVersion(candidate) && compareTourVersions(candidate, current) === 1;
}

export function releaseUrl(tag: string): string {
  const channel = tag.startsWith(VIEWER_TAG_PREFIX) ? 'viewer' : 'ctl';
  return versionFromTag(tag, channel) ? `${RELEASE_BASE}/tag/${encodeURIComponent(tag)}` : RELEASE_BASE;
}

export function stableRelease(value: unknown, channel: ReleaseChannel = 'ctl'): ViewerRelease | undefined {
  if (!value || typeof value !== 'object') return;
  const release = value as Record<string, unknown>;
  if (release.draft !== false || release.prerelease !== false || typeof release.tag_name !== 'string') return;
  const version = versionFromTag(release.tag_name, channel);
  if (version && isStableTourVersion(version)) return { tag: release.tag_name, version };
}

async function fetchLatestRelease(channel: ReleaseChannel, fetchRelease: typeof fetch, signal: AbortSignal): Promise<ViewerRelease | undefined> {
  const request = async (url: string) => {
    if (signal.aborted) throw new Error('Release check timed out');
    const response = await fetchRelease(url, {
      credentials: 'omit', referrerPolicy: 'no-referrer', priority: 'low', signal,
      headers: { Accept: 'application/vnd.github+json' }
    });
    if (!response.ok) throw new Error('Release check failed');
    return response;
  };

  if (channel === 'ctl') {
    const response = await request(RELEASE_API);
    const release = stableRelease(await response.json());
    if (!release) throw new Error('Invalid release');
    return release;
  }

  let latest: ViewerRelease | undefined;
  for (let page = 1; ; page++) {
    const response = await request(`${VIEWER_RELEASES_API}?per_page=100&page=${page}`);
    const releases: unknown = await response.json();
    if (!Array.isArray(releases)) throw new Error('Invalid release list');
    for (const value of releases) {
      const release = stableRelease(value, 'viewer');
      if (release && (!latest || isNewerRelease(release.version, latest.version))) latest = release;
    }
    // Read pagination from the Link header and build each request from the repository's release endpoint.
    if (!response.headers.get('link')?.includes('rel="next"')) return latest;
  }
}

interface ReleaseCache { checkedAt: number; retryAt: number; release?: ViewerRelease }
interface CheckerOptions {
  channel?: ReleaseChannel;
  fetch: typeof fetch;
  storage?: Pick<Storage, 'getItem' | 'setItem'>;
  now?: () => number;
  timeoutMs?: number;
}

// One checker per App lifetime; in-flight calls and workspace changes share the same request.
export function createReleaseChecker({ channel = 'ctl', fetch: fetchRelease, storage, now = Date.now, timeoutMs = 6000 }: CheckerOptions) {
  const cacheKey = channel === 'ctl' ? RELEASE_CACHE_KEY : VIEWER_RELEASE_CACHE_KEY;
  let cache: ReleaseCache = { checkedAt: 0, retryAt: 0 };
  let pending: Promise<ViewerRelease | undefined> | undefined;
  try {
    const raw = storage?.getItem(cacheKey);
    const stored = raw ? JSON.parse(raw) : undefined;
    const timestamp = now();
    if (stored && Number.isFinite(stored.checkedAt) && stored.checkedAt > 0 && stored.checkedAt <= timestamp &&
        Number.isFinite(stored.retryAt) && stored.retryAt <= timestamp + RELEASE_CACHE_MS) {
      const release = stableRelease({ tag_name: stored.release?.tag, draft: false, prerelease: false }, channel);
      if (stored.release === undefined || release) cache = { checkedAt: stored.checkedAt, retryAt: stored.retryAt, release };
    }
  } catch { /* Storage can be unavailable in an embedded webview. */ }
  const save = () => {
    try { storage?.setItem(cacheKey, JSON.stringify(cache)); } catch { /* Use the in-memory cache. */ }
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
            fetchLatestRelease(channel, fetchRelease, controller.signal),
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

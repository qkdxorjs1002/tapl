import { useEffect, useState } from 'react';
import { version as viewerVersion } from '../../package.json';
import { useI18n } from './i18n';
import { createReleaseChecker, isNewerRelease, releaseUrl, RELEASE_RETRY_MS } from './viewerRelease';

export function ViewerVersion(): JSX.Element {
  const { t } = useI18n();
  const [checker] = useState(() => {
    let storage: Storage | undefined;
    try { storage = window.localStorage; } catch { /* Private/sandboxed storage is optional. */ }
    return createReleaseChecker({ fetch: (...args) => globalThis.fetch(...args), storage });
  });
  const [release, setRelease] = useState(checker.cached);
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || document.visibilityState !== 'hidden');
  useEffect(() => {
    let mounted = true;
    const check = () => {
      const showing = document.visibilityState !== 'hidden';
      setVisible(showing);
      if (showing) void checker.check().then(value => { if (mounted) setRelease(value); });
    };
    check();
    document.addEventListener('visibilitychange', check);
    const timer = window.setInterval(check, RELEASE_RETRY_MS);
    return () => { mounted = false; document.removeEventListener('visibilitychange', check); window.clearInterval(timer); };
  }, [checker]);
  const update = release && isNewerRelease(release.version, viewerVersion) ? release : undefined;
  const currentLabel = t('viewerVersionRelease', { version: viewerVersion });
  const updateLabel = update ? t('viewerVersionUpdate', { current: viewerVersion, latest: update.version }) : undefined;
  return (
    <footer className="tapl-viewer-version" data-update={!!update} data-visible={visible}>
      <span className="tapl-viewer-version-pill">
        <a className="tapl-viewer-version-current" href={releaseUrl(viewerVersion)}
          target="_blank" rel="noopener noreferrer" aria-label={currentLabel} title={currentLabel}>
          v{viewerVersion}
        </a>
        {update && <>
          <span className="tapl-viewer-version-arrow" aria-hidden="true">→</span>
          <a className="tapl-viewer-version-latest" href={releaseUrl(update.tag)}
            target="_blank" rel="noopener noreferrer" aria-label={updateLabel} title={updateLabel}>
            v{update.version}
          </a>
        </>}
      </span>
    </footer>
  );
}

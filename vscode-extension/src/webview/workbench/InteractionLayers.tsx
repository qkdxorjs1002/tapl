import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useBrowserLayoutEffect } from './effects';
import { useDialogMotion } from './workbenchMotion';
import { useI18n } from '../i18n';
import type { WorkspaceDirectoryResult, WorkspaceSelectionResult } from '../types';
import { Icon } from './Icon';

/** One tooltip layer also covers icon controls in flyouts and native dialogs. */
export function IconTooltips({ navigationKey }: { navigationKey: string }): JSX.Element | null {
  const id = useId();
  const tip = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const active = useRef<HTMLElement>();
  const nativeTitle = useRef<string | null>(null);
  const [shown, setShown] = useState<{ label: string; target: HTMLElement }>();
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const clear = () => {
    clearTimeout(timer.current);
    const target = active.current;
    if (target) {
      const description = (target.getAttribute('aria-describedby') ?? '')
        .split(/\s+/)
        .filter((value) => value && value !== id)
        .join(' ');
      if (description) target.setAttribute('aria-describedby', description);
      else target.removeAttribute('aria-describedby');
      if (nativeTitle.current !== null && !target.hasAttribute('title'))
        target.setAttribute('title', nativeTitle.current);
    }
    active.current = undefined;
    nativeTitle.current = null;
    setShown(undefined);
  };
  useEffect(() => {
    clear();
  }, [navigationKey]);
  useEffect(() => {
    const candidate = (node: EventTarget | null) => {
      if (!(node instanceof Element)) return;
      const target = node.closest<HTMLElement>('button[aria-label],summary[aria-label]');
      if (
        !target ||
        !target.closest('.tapl-workbench,.wb-explore-panel,dialog.wb-dialog') ||
        target.matches(':disabled')
      )
        return;
      if (target.dataset.wbTooltip === 'false') return;
      if (target.dataset.wbTooltip === 'true') return target;
      const copy = target.cloneNode(true) as HTMLElement;
      copy.querySelectorAll('svg,[aria-hidden="true"],.wb-sr-only,.sr-only').forEach((element) => element.remove());
      return copy.textContent?.trim() ? undefined : target;
    };
    const open = (target: HTMLElement, immediately = false) => {
      if (active.current === target && !immediately) return;
      clear();
      active.current = target;
      nativeTitle.current = target.getAttribute('title');
      target.removeAttribute('title');
      const show = () => {
        if (!target.isConnected || active.current !== target) return;
        target.setAttribute(
          'aria-describedby',
          [target.getAttribute('aria-describedby'), id].filter(Boolean).join(' ')
        );
        setShown({ label: target.getAttribute('aria-label') ?? '', target });
      };
      if (immediately) show();
      else timer.current = setTimeout(show, 300);
    };
    const over = (event: PointerEvent) => {
      if (event.pointerType !== 'touch') {
        const target = candidate(event.target);
        if (target) open(target);
      }
    };
    const out = (event: PointerEvent) => {
      if (
        active.current &&
        !active.current.contains(event.relatedTarget as Node | null) &&
        document.activeElement !== active.current
      )
        clear();
    };
    const focus = (event: FocusEvent) => {
      const target = candidate(event.target);
      if (target) open(target, true);
    };
    const blur = (event: FocusEvent) => {
      if (active.current && !active.current.contains(event.relatedTarget as Node | null)) clear();
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') clear();
    };
    document.addEventListener('pointerover', over);
    document.addEventListener('pointerout', out);
    document.addEventListener('focusin', focus);
    document.addEventListener('focusout', blur);
    document.addEventListener('pointerdown', clear, true);
    document.addEventListener('click', clear, true);
    document.addEventListener('keydown', key);
    document.addEventListener('scroll', clear, true);
    window.addEventListener('resize', clear);
    return () => {
      clear();
      document.removeEventListener('pointerover', over);
      document.removeEventListener('pointerout', out);
      document.removeEventListener('focusin', focus);
      document.removeEventListener('focusout', blur);
      document.removeEventListener('pointerdown', clear, true);
      document.removeEventListener('click', clear, true);
      document.removeEventListener('keydown', key);
      document.removeEventListener('scroll', clear, true);
      window.removeEventListener('resize', clear);
    };
  }, [id]);
  useBrowserLayoutEffect(() => {
    if (!shown || !tip.current) return;
    const anchor = shown.target.getBoundingClientRect(),
      rect = tip.current.getBoundingClientRect();
    const below = anchor.bottom + 8;
    setPosition({
      left: Math.max(8, Math.min(anchor.left + (anchor.width - rect.width) / 2, innerWidth - rect.width - 8)),
      top: below + rect.height < innerHeight - 8 ? below : Math.max(8, anchor.top - rect.height - 8)
    });
  }, [shown]);
  return shown
    ? createPortal(
        <div ref={tip} id={id} role="tooltip" className="wb-tooltip" style={position}>
          {shown.label}
        </div>,
        shown.target.closest('dialog') ?? document.body
      )
    : null;
}

export function WorkspaceDialog({
  open,
  workspace,
  message,
  result,
  directoryResult,
  browse,
  submit,
  close,
  fallbackFocus
}: {
  open: boolean;
  workspace?: string;
  message?: string;
  result?: WorkspaceSelectionResult;
  directoryResult?: WorkspaceDirectoryResult;
  browse: (requestId: string, path?: string) => void;
  submit: (workspace: string) => void;
  close: () => void;
  fallbackFocus: () => HTMLElement | null;
}): JSX.Element | null {
  const { t } = useI18n();
  const dialog = useRef<HTMLDialogElement>(null);
  const [path, setPath] = useState(workspace ?? '');
  const [pending, setPending] = useState(false),
    [error, setError] = useState('');
  const pendingRef = useRef(false);
  const request = useRef('');
  const requestPrefix = useId();
  const requestSequence = useRef(0);
  const edits = useRef(0);
  const requestedEdit = useRef(0);
  const [listing, setListing] = useState<WorkspaceDirectoryResult>();
  const [browsing, setBrowsing] = useState(false);
  const [browseError, setBrowseError] = useState('');
  const folderList = useRef<HTMLDivElement>(null);
  const initialFocus = useRef<HTMLButtonElement>(null);
  const loadDirectory = (candidate?: string) => {
    const requestId = `${requestPrefix}:${++requestSequence.current}`;
    request.current = requestId;
    requestedEdit.current = edits.current;
    setBrowsing(true);
    setBrowseError('');
    setError('');
    browse(requestId, candidate);
  };
  const present = useDialogMotion(open, dialog, initialFocus, fallbackFocus);
  useBrowserLayoutEffect(() => {
    if (!open) return;
    setPath(workspace ?? '');
    setError(message ?? '');
    setPending(false);
    pendingRef.current = false;
    setListing(undefined);
    loadDirectory(workspace || undefined);
    return () => { request.current = ''; };
  }, [open]);
  useEffect(() => {
    if (!open || !directoryResult || directoryResult.requestId !== request.current) return;
    setBrowsing(false);
    if (directoryResult.ok) {
      setListing(directoryResult);
      if (edits.current === requestedEdit.current) setPath(directoryResult.path ?? '');
      folderList.current?.scrollTo(0, 0);
    } else setBrowseError(directoryResult.message ?? t('taplUnavailable'));
  }, [directoryResult, open]);
  useEffect(() => {
    if (!listing?.path || !folderList.current) return;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const animation = folderList.current.animate([{ opacity: 0.5 }, { opacity: 1 }], { duration: 140 });
    return () => animation.cancel();
  }, [listing]);
  useEffect(() => {
    if (!result || !open || !pendingRef.current) return;
    setPending(false);
    pendingRef.current = false;
    if (result.ok) close();
    else setError(result.message ?? t('taplUnavailable'));
  }, [result]);
  const cancel = () => {
    if (open && !pendingRef.current) close();
  };
  if (!present) return null;
  return (
    <dialog
      ref={dialog}
      className="wb-dialog wb-workspace-dialog"
      data-wb-motion="presence"
      aria-hidden={!open}
      aria-labelledby="wb-workspace-title"
      aria-busy={pending}
      onCancel={(event) => {
        event.preventDefault();
        cancel();
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const rect = event.currentTarget.getBoundingClientRect();
        if (
          event.clientX < rect.left ||
          event.clientX > rect.right ||
          event.clientY < rect.top ||
          event.clientY > rect.bottom
        )
          cancel();
      }}
    >
      <div className="wb-dialog-heading">
        <h2 id="wb-workspace-title">{t('chooseWorkspace')}</h2>
        <button
          type="button"
          className="btn btn-ghost btn-sm btn-square"
          aria-label={t('wbClose')}
          disabled={pending}
          onClick={cancel}
        >
          <Icon name="close" />
        </button>
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!path.trim() || pendingRef.current || browsing) return;
          pendingRef.current = true;
          setPending(true);
          setError('');
          submit(path.trim());
        }}
      >
        <p className="wb-workspace-hint">{t('workspaceBrowseHelp')}</p>
        <div className="wb-folder-toolbar">
          <button ref={initialFocus} type="button" className="btn btn-sm btn-ghost" disabled={pending}
            onClick={() => loadDirectory('~')}><Icon name="folder" />{t('workspaceHome')}</button>
        </div>
        <div className="wb-folder-location" title={listing?.path}>{listing?.path ?? t('workspaceFolders')}</div>
        <div ref={folderList} className="wb-folder-list" role="region" aria-label={t('workspaceFolders')} aria-busy={browsing}>
          <ul>
              {listing?.parent && <li><button type="button" className="wb-folder-row" disabled={pending || browsing}
                aria-label={t('workspaceParent')} title={t('workspaceParent')} onClick={() => loadDirectory(listing.parent ?? undefined)}>
                <Icon name="folder" /><span>../</span><Icon name="chevron" /></button></li>}
              {browsing ? <li className="wb-folder-empty" role="status"><span className="loading loading-spinner loading-sm" /> {t('workspaceLoading')}</li>
                : browseError ? <li className="wb-folder-empty wb-dialog-error" role="alert">{browseError}</li>
                : !listing?.directories?.length && <li className="wb-folder-empty">{t('workspaceEmpty')}</li>}
              {!browsing && !browseError && listing?.directories?.map((folder) => (
              <li key={folder.path}><button type="button" className="wb-folder-row" disabled={pending}
                onClick={() => loadDirectory(folder.path)}><Icon name="folder" /><span>{folder.name}</span><Icon name="chevron" /></button></li>
            ))}</ul>
        </div>
        <label className="wb-dialog-label" htmlFor="tapl-workspace-path">
          {t('workspacePath')}
        </label>
        <div className="wb-folder-path">
          <input
            id="tapl-workspace-path"
            className="input wb-dialog-input"
            value={path}
            placeholder={t('workspacePlaceholder')}
            autoComplete="off"
            disabled={pending || browsing}
            aria-invalid={!!error}
            aria-describedby={error ? 'wb-workspace-error' : undefined}
            onChange={(event) => {
              edits.current += 1;
              setPath(event.target.value);
              setError('');
            }}
          />
          <button type="button" className="btn btn-sm btn-ghost" disabled={pending || browsing || !path.trim()}
            onClick={() => loadDirectory(path.trim())}>{t('workspaceGo')}</button>
        </div>
        <p className="wb-workspace-hint">{t('workspaceSetupHint')}</p>
        {error && (
          <p id="wb-workspace-error" className="wb-dialog-error" role="alert">
            {error}
          </p>
        )}
        <div className="wb-dialog-actions">
          <button type="button" className="btn btn-sm btn-ghost" disabled={pending} onClick={cancel}>
            {t('cancel')}
          </button>
          <button type="submit" className="btn btn-sm btn-primary" disabled={pending || browsing || !path.trim()}>
            {pending && <span className="loading loading-spinner loading-xs" />}
            {t('openWorkspace')}
          </button>
        </div>
      </form>
    </dialog>
  );
}

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useBrowserLayoutEffect } from './effects';
import type { SupportedLocale } from '../../i18n';
import { I18nProvider, useI18n } from '../i18n';
import type {
  DisplayLayout,
  RunDiscardResult,
  TaplItem,
  TaplRunSnapshot,
  TaplSearchResult,
  TaplWorkflowRun,
  WebviewCommand,
  WebviewView,
  WorkspaceSelectionResult
} from '../types';
import { Icon } from './Icon';
import { IconTooltips, WorkspaceDialog } from './InteractionLayers';
import { PageLoading } from './SecondaryViews';
import { Explore } from './Explore';
import { EmptyState, NavCount, PageHeading } from './components';
import { CurrentRun, TaskStatus } from './RunViews';
import { RecordsView } from './RecordsView';
import { commandForRun, useWorkbench } from './useWorkbench';
import { recordRunKey, routeIdentity, runKey, runTitle, tabRuns, taskCounts, type WorkbenchPage } from './model';

export interface WorkbenchProps {
  view: WebviewView;
  layout: DisplayLayout;
  memorySupported: boolean;
  discardSupported: boolean;
  discardResult?: RunDiscardResult;
  send: (command: WebviewCommand) => void;
  renderPage: (view: WebviewView, send: (command: WebviewCommand) => void, back?: () => void) => ReactNode;
  loading?: boolean;
  workspaceResult?: WorkspaceSelectionResult;
  renderManagement?: (run: TaplWorkflowRun | undefined, context?: TaplRunSnapshot) => ReactNode;
  locale: SupportedLocale;
  onLocaleChange: (locale: SupportedLocale) => void;
  initialState?: unknown;
  onStateChange?: (state: unknown) => void;
  browser?: boolean;
  workspace?: string;
}
export function Workbench(props: WorkbenchProps): JSX.Element {
  return (
    <I18nProvider locale={props.locale}>
      <WorkbenchShell {...props} />
    </I18nProvider>
  );
}
function WorkbenchShell(props: WorkbenchProps): JSX.Element {
  const { t } = useI18n();
  const pageRef = useRef<HTMLElement>(null);
  const [workspaceOpen, setWorkspaceOpen] = useState(props.view.type === 'workspace');
  const stableView = useRef<WebviewView>(
    props.view.type === 'workspace'
      ? {
          type: 'overview',
          archives: [],
          searchQuery: '',
          status: {
            active_run: null,
            task_counts: {},
            incomplete_tasks: 0,
            plans: [],
            tasks: [],
            findings: [],
            recent_events: [],
            schema: {}
          }
        }
      : props.view
  );
  if (props.view.type !== 'workspace') stableView.current = props.view;
  const visibleView = props.view.type === 'workspace' ? stableView.current : props.view;
  useEffect(() => {
    if (props.view.type === 'workspace' && props.browser) setWorkspaceOpen(true);
  }, [props.view]);

  const sidebarRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout>>();
  const [sidebarPinned, setSidebarPinned] = useState(
    () => (props.initialState as { sidebarPinned?: unknown } | undefined)?.sidebarPinned === true
  );
  const [sidebarHovered, setSidebarHovered] = useState(false);
  const [sidebarFocused, setSidebarFocused] = useState(false);
  const [exploreActive, setExploreActive] = useState(false);
  const pinnedRef = useRef(sidebarPinned);
  pinnedRef.current = sidebarPinned;
  const languageRef = useRef<HTMLDetailsElement>(null);
  const [theme, setTheme] = useState<'light' | 'dark' | undefined>(() => {
    const restored = props.initialState as { theme?: unknown } | undefined;
    return restored?.theme === 'light' || restored?.theme === 'dark' ? restored.theme : undefined;
  });
  const [systemDark, setSystemDark] = useState(
    () =>
      typeof document !== 'undefined' &&
      (props.browser
        ? matchMedia('(prefers-color-scheme: dark)').matches
        : document.body.classList.contains('vscode-dark') || document.body.classList.contains('vscode-high-contrast'))
  );
  const darkTheme = theme ? theme === 'dark' : systemDark;
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const update = () =>
      setSystemDark(
        props.browser
          ? media.matches
          : document.body.classList.contains('vscode-dark') || document.body.classList.contains('vscode-high-contrast')
      );
    const observer = new MutationObserver(update);
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    media.addEventListener('change', update);
    update();
    return () => {
      observer.disconnect();
      media.removeEventListener('change', update);
    };
  }, [props.browser]);
  const themeRef = useRef(theme);
  themeRef.current = theme;
  const persistRef = useRef(props.onStateChange);
  persistRef.current = props.onStateChange;
  const [mobile, setMobile] = useState(
    () => props.layout === 'small' || (typeof matchMedia === 'function' && matchMedia('(max-width: 800px)').matches)
  );
  const [menuOpen, setMenuOpen] = useState(false);
  const navigation = useWorkbench({
    ...props,
    view: visibleView,
    pageRef,
    sidebarRef,
    onStateChange: (state) =>
      persistRef.current?.({ ...(state as object), theme: themeRef.current, sidebarPinned: pinnedRef.current })
  });
  const { state, prefs, snapshot, selectedRun, activeRuns } = navigation;
  const selectedKey = state.route.runKey;
  const tabs = tabRuns(activeRuns, selectedRun);
  const counts = taskCounts(snapshot);
  const currentLegacy = state.route.view;
  const memoryPage = state.route.page === 'memories' || currentLegacy?.type === 'memorySource';
  const page = state.route.page;
  const back = state.trail.length ? navigation.goBack : undefined;
  const isPending = !!state.pending;
  const sidebarExpanded = mobile || sidebarPinned || sidebarHovered || sidebarFocused || exploreActive;
  const closeMenu = (returnFocus = false) => {
    setMenuOpen(false);
    if (returnFocus) menuRef.current?.focus({ preventScroll: true });
  };
  useEffect(() => {
    const query = matchMedia('(max-width: 800px)');
    const resize = () => {
      const narrow = props.layout === 'small' || query.matches;
      setMobile(narrow);
      setMenuOpen(false);
    };
    resize();
    query.addEventListener('change', resize);
    return () => query.removeEventListener('change', resize);
  }, [props.layout]);
  useEffect(() => {
    const focus = () => {
      const element = document.activeElement;
      const inNavigation = sidebarRef.current?.contains(element) || element?.closest('#wb-explore-panel');
      setSidebarFocused(!!inNavigation && !!element?.matches(':focus-visible'));
      if (!sidebarRef.current?.matches(':hover')) {
        clearTimeout(hoverTimer.current);
        hoverTimer.current = setTimeout(() => setSidebarHovered(false), 600);
      }
    };
    const pointer = (event: PointerEvent) => {
      setSidebarFocused(false);
      const target = event.target;
      if (
        (target instanceof Node && sidebarRef.current?.contains(target)) ||
        (target instanceof Element && target.closest('#wb-explore-panel,.wb-navigation-pin'))
      )
        return;
      clearTimeout(hoverTimer.current);
      setSidebarHovered(false);
      setExploreActive(false);
    };
    document.addEventListener('focusin', focus);
    document.addEventListener('pointerdown', pointer, true);
    return () => {
      clearTimeout(hoverTimer.current);
      document.removeEventListener('focusin', focus);
      document.removeEventListener('pointerdown', pointer, true);
    };
  }, []);
  useEffect(() => {
    clearTimeout(hoverTimer.current);
    setSidebarHovered(false);
    setSidebarFocused(false);
  }, [mobile]);
  useBrowserLayoutEffect(() => {
    if (sidebarRef.current) sidebarRef.current.inert = mobile && !menuOpen;
    if (pageRef.current) pageRef.current.inert = mobile && menuOpen;
  }, [mobile, menuOpen]);
  useEffect(() => {
    const root = document.documentElement;
    if (theme) root.dataset.taplTheme = theme;
    else if (props.browser) root.dataset.taplTheme = systemDark ? 'dark' : 'light';
    else delete root.dataset.taplTheme;
    persistRef.current?.({ version: 1, pages: state.pages, theme, sidebarPinned });
  }, [theme, props.browser, systemDark, sidebarPinned]);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.key !== 'Escape') return;
      if (languageRef.current?.open) {
        languageRef.current.open = false;
        languageRef.current.querySelector<HTMLElement>('summary')?.focus();
      } else if (mobile && menuOpen) closeMenu(true);
    };
    const outside = (event: PointerEvent) => {
      if (languageRef.current?.open && !languageRef.current.contains(event.target as Node))
        languageRef.current.open = false;
    };
    document.addEventListener('keydown', escape);
    document.addEventListener('pointerdown', outside);
    return () => {
      document.removeEventListener('keydown', escape);
      document.removeEventListener('pointerdown', outside);
    };
  }, [mobile, menuOpen]);
  useEffect(() => {
    closeMenu();
  }, [selectedKey, page]);
  const selectPage = (target: WorkbenchPage) => {
    if (target === 'memories' && !props.memorySupported) navigation.go({ page: 'memories', runKey: selectedKey });
    else navigation.selectPage(target);
    closeMenu();
  };
  const openItem = (item: TaplItem | TaplSearchResult, sourceRun?: TaplWorkflowRun) => {
    if (item.id == null) return;
    const key = sourceRun
      ? runKey(sourceRun)
      : 'run_id' in item && typeof item.run_id === 'string'
        ? recordRunKey(item.source_db, item.run_id)
        : selectedKey;
    navigation.go(
      { page: 'legacy', runKey: key },
      {
        command: 'openSearchResult',
        itemId: item.id,
        source_db: item.source_db ?? sourceRun?.source_db ?? selectedRun?.source_db
      },
      true
    );
    closeMenu();
  };
  const openRun = (run: TaplWorkflowRun, internal: boolean) => {
    if (!internal) {
      navigation.switchRun(run);
      closeMenu();
      return;
    }
    const command = commandForRun(run, activeRuns);
    navigation.go({ page: 'current', runKey: runKey(run) }, command, internal, run);
    closeMenu();
  };
  const navButton = (
    target: WorkbenchPage,
    icon: string,
    title: string,
    counter?: { count: number; percentage?: boolean }
  ) => (
    <button
      type="button"
      className="wb-nav-button"
      aria-label={[
        title,
        counter
          ? counter.percentage
            ? `${counter.count}%`
            : t(counter.count === 1 ? 'wbItem' : 'wbItems', { count: counter.count })
          : undefined
      ]
        .filter(Boolean)
        .join(' · ')}
      data-wb-tooltip={!mobile && !sidebarPinned ? 'true' : 'false'}
      aria-current={page === target || (target === 'memories' && memoryPage) ? 'page' : undefined}
      onClick={() => selectPage(target)}
      data-wb-focus={`nav:${target}`}
    >
      <Icon name={icon} />
      <span className="wb-nav-label" aria-hidden="true">
        {title}
      </span>
      {counter != null && <NavCount {...counter} className="wb-nav-counter" />}
    </button>
  );
  const shownView = currentLegacy ?? (page === 'legacy' && !isPending ? visibleView : undefined);
  const sendPage = (command: WebviewCommand) => {
    if (command.command === 'chooseWorkspace') {
      if (props.browser) {
        setWorkspaceOpen(true);
        setMenuOpen(false);
      } else props.send(command);
      return;
    }
    navigation.wrappedSend(command);
  };

  return (
    <div
      className="tapl-workbench"
      data-layout={props.layout}
      data-mobile={mobile}
      data-menu-open={menuOpen}
      data-sidebar-pinned={sidebarPinned}
      data-sidebar-expanded={sidebarExpanded}
    >
      <a
        className="wb-skip-link"
        href="#wb-page-content"
        onClick={(event) => {
          event.preventDefault();
          (
            pageRef.current?.querySelector<HTMLElement>('[data-wb-page-heading]') ??
            document.getElementById('wb-page-content')
          )?.focus();
        }}
      >
        {t('wbSkip')}
      </a>
      <header className="wb-topbar">
        <div className="wb-brand-area">
          <button
            ref={menuRef}
            type="button"
            className="btn btn-ghost btn-sm btn-square wb-mobile-menu"
            aria-controls="wb-sidebar"
            aria-expanded={menuOpen}
            aria-label={t(menuOpen ? 'wbMenuClose' : 'wbNavigation')}
            onClick={() => setMenuOpen((value) => !value)}
          >
            <Icon name={menuOpen ? 'close' : 'menu'} />
          </button>
          <button type="button" className="wb-brand" aria-label="tapl" onClick={() => selectPage('current')}>
            tapl
          </button>
          <div className="wb-brand-actions">
            <details className="dropdown wb-language-menu" ref={languageRef}>
              <summary className="btn btn-ghost btn-sm btn-square" aria-label={t('wbLanguage')}>
                <Icon name="languages" />
              </summary>
              <ul className="menu dropdown-content wb-language-options">
                {(['ko', 'en'] as const).map((locale) => (
                  <li key={locale}>
                    <button
                      type="button"
                      lang={locale}
                      aria-pressed={props.locale === locale}
                      onClick={() => {
                        props.onLocaleChange(locale);
                        if (languageRef.current) languageRef.current.open = false;
                        languageRef.current?.querySelector<HTMLElement>('summary')?.focus();
                      }}
                    >
                      {locale === 'ko' ? '한국어' : 'English'}
                      {props.locale === locale && <Icon name="check" />}
                    </button>
                  </li>
                ))}
              </ul>
            </details>
            <button
              type="button"
              className="btn btn-ghost btn-sm btn-square"
              aria-label={t(darkTheme ? 'wbLight' : 'wbDark')}
              data-wb-focus="theme-toggle"
              onClick={() => {
                setTheme(darkTheme ? 'light' : 'dark');
              }}
            >
              <Icon name={darkTheme ? 'sun' : 'moon'} />
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm btn-square wb-navigation-pin"
              data-wb-focus="sidebar-pin"
              aria-label={t(sidebarPinned ? 'wbUnpinNavigation' : 'wbPinNavigation')}
              aria-pressed={sidebarPinned}
              aria-controls="wb-sidebar"
              onClick={() => setSidebarPinned((value) => !value)}
            >
              <Icon name={sidebarPinned ? 'panel-collapse' : 'panel-expand'} />
            </button>
          </div>
        </div>
        <nav className="wb-run-tabs tabs" role="tablist" aria-label="RUN">
          {tabs.map((run, index) => {
            const key = runKey(run),
              selected = key === selectedKey;
            const temporary = !activeRuns.some((candidate) => runKey(candidate) === key);
            return (
              <button
                type="button"
                role="tab"
                key={key}
                className={`tab wb-run-tab ${temporary ? 'wb-run-tab-temporary' : ''}`}
                aria-selected={selected}
                aria-controls="wb-page-content"
                id={`wb-run-tab-${index}`}
                tabIndex={
                  selected || (index === 0 && !tabs.some((candidate) => runKey(candidate) === selectedKey)) ? 0 : -1
                }
                title={[runTitle(run), run.id, run.source_db].filter(Boolean).join('\n')}
                data-wb-focus={`run:${key}`}
                onClick={() => openRun(run, false)}
                onKeyDown={(event) => {
                  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
                  event.preventDefault();
                  const next =
                    event.key === 'Home'
                      ? 0
                      : event.key === 'End'
                        ? tabs.length - 1
                        : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
                  openRun(tabs[next], false);
                  document.getElementById(`wb-run-tab-${next}`)?.focus({ preventScroll: true });
                }}
              >
                <span className="wb-run-tab-title">
                  <span className="wb-tab-dot" aria-hidden="true" />
                  <span>{runTitle(run)}</span>
                  {temporary && <Icon name="lock" />}
                </span>
                <span className="wb-run-tab-meta">
                  {run.slug && run.slug !== 'active' ? run.slug : run.id?.slice(0, 8)}
                </span>
              </button>
            );
          })}
        </nav>
      </header>
      <aside
        ref={sidebarRef}
        id="wb-sidebar"
        className="wb-sidebar"
        aria-label={t('wbNavigation')}
        onPointerEnter={(event) => {
          if (event.pointerType === 'mouse' && !mobile && event.currentTarget.contains(event.target as Node)) {
            clearTimeout(hoverTimer.current);
            setSidebarHovered(true);
          }
        }}
        onPointerLeave={() => {
          clearTimeout(hoverTimer.current);
          hoverTimer.current = setTimeout(() => setSidebarHovered(false), 600);
        }}
      >
        <section>
          {props.workspace && !props.browser && (
            <button
              type="button"
              className="wb-workspace-switch"
              title={props.workspace}
              aria-label={t('changeWorkspace')}
              onClick={() => props.send({ command: 'chooseWorkspace' })}
            >
              <Icon name="folder" />
              <span className="wb-nav-label" aria-hidden="true">
                {props.workspace.split(/[\\/]/).filter(Boolean).pop()}
              </span>
              <Icon name="chevron" />
            </button>
          )}
          <div className="wb-section-heading wb-workspace-heading">
            <h2 className="wb-nav-caption">{t('wbWorkspace')}</h2>
            {props.browser && (
              <button
                type="button"
                className="btn btn-ghost btn-xs btn-square"
                aria-label={t('changeWorkspace')}
                title={[t('changeWorkspace'), props.workspace].filter(Boolean).join(' · ')}
                onClick={() => {
                  setMenuOpen(false);
                  setWorkspaceOpen(true);
                }}
                data-wb-focus="workspace-picker"
              >
                <Icon name="folder" />
              </button>
            )}
          </div>
          <nav className="menu wb-main-menu">
            {navButton(
              'current',
              'focus',
              t('wbCurrent'),
              snapshot ? { count: counts.percent, percentage: true } : undefined
            )}
            {navButton('tasks', 'table', t('wbTasks'), snapshot ? { count: counts.total } : undefined)}
          </nav>
        </section>
        <section>
          <h2 className="wb-nav-caption">{t('wbExplore')}</h2>
          <Explore
            snapshot={snapshot}
            enabled={!mobile || menuOpen}
            mobile={mobile}
            sidebarRef={sidebarRef}
            menuRef={menuRef}
            prefs={prefs}
            update={navigation.changePage}
            openItem={openItem}
            navigationKey={routeIdentity(state.route)}
            onActiveChange={setExploreActive}
          />
        </section>
        <div className="wb-sidebar-bottom">
          <section>
            <h2 className="wb-nav-caption">{t('wbMemory')}</h2>
            <nav className="menu wb-main-menu">
              {navButton('records', 'search', t('wbRecords'))}
              {navButton('memories', 'book', t('wbMemories'))}
            </nav>
          </section>
          <section className="wb-management">
            <div className="wb-section-heading">
              <h2 className="wb-nav-caption">{t('wbManagement')}</h2>
              <div className="wb-management-actions">
                <button
                  type="button"
                  className="btn btn-ghost btn-xs btn-square"
                  aria-label={t('debug')}
                  title={t('debug')}
                  onClick={() => navigation.wrappedSend({ command: 'debug' })}
                >
                  <Icon name="debug" />
                </button>
              </div>
            </div>
            {props.renderManagement ? (
              props.renderManagement(selectedRun, snapshot)
            ) : (
              <button type="button" className="wb-nav-button wb-discard-button" aria-label={t('wbDiscard')} disabled>
                <Icon name="trash" />
                <span className="wb-nav-label" aria-hidden="true">
                  {t('wbDiscard')}
                </span>
              </button>
            )}
          </section>
        </div>
      </aside>
      <main
        ref={pageRef}
        className="wb-page-scroll"
        data-current-mindmap={page === 'current' && !!snapshot && !props.loading}
        data-memory-mindmap={
          (page === 'memories' || page === 'legacy') && shownView?.type === 'memories' && props.memorySupported && !props.loading
        }
      >
        <div
          id="wb-page-content"
          className="wb-page-content"
          role="tabpanel"
          aria-labelledby={
            tabs.some((run) => runKey(run) === selectedKey)
              ? `wb-run-tab-${tabs.findIndex((run) => runKey(run) === selectedKey)}`
              : undefined
          }
          tabIndex={-1}
        >
          {props.loading ? (
            <PageLoading />
          ) : (
            <>
              {page === 'current' &&
                (isPending && !snapshot ? (
                  <>
                    <PageHeading title={t('wbCurrent')} back={back} />
                    <p className="wb-loading-line" role="status">
                      {t('wbLoadingRun')}
                    </p>
                  </>
                ) : (
                  <CurrentRun snapshot={snapshot} title={t('wbCurrent')} open={openItem} back={back} />
                ))}
              {page === 'tasks' && (
                <TaskStatus
                  snapshot={snapshot}
                  prefs={prefs}
                  update={navigation.changePage}
                  open={openItem}
                  back={back}
                />
              )}
              {page === 'records' && (
                <RecordsView
                  view={currentLegacy?.type === 'records' ? currentLegacy : undefined}
                  prefs={prefs}
                  run={selectedRun}
                  update={navigation.changePage}
                  request={(command) =>
                    navigation.go(
                      {
                        page: 'records',
                        runKey: selectedKey,
                        view: currentLegacy?.type === 'records' ? currentLegacy : undefined
                      },
                      command,
                      'replace'
                    )
                  }
                  open={openItem}
                  openRun={(run) => openRun(run, true)}
                  back={back}
                  loading={isPending}
                />
              )}
              {page === 'management' && (
                <>
                  <PageHeading title={t('wbDiscard')} back={back} />
                  {props.renderManagement ? (
                    props.renderManagement(selectedRun, snapshot)
                  ) : (
                    <EmptyState title={t('wbEmptyManagement')} />
                  )}
                </>
              )}
              {page === 'memories' && !props.memorySupported && (
                <>
                  <PageHeading title={t('wbMemories')} back={back} />
                  <EmptyState title={t('memoryUnsupported')} icon="book" />
                </>
              )}
              {((page === 'memories' && props.memorySupported) || page === 'legacy') && (
                <>
                  {isPending && !shownView && <PageLoading back={back} />}
                  {shownView && <div className="wb-route-view">{props.renderPage(shownView, sendPage, back)}</div>}
                </>
              )}
            </>
          )}
        </div>
      </main>
      {props.browser && (
        <WorkspaceDialog
          open={workspaceOpen}
          workspace={props.view.type === 'workspace' ? props.view.workspace || props.workspace : props.workspace}
          message={props.view.type === 'workspace' ? props.view.message : undefined}
          result={props.workspaceResult}
          submit={(workspace) => props.send({ command: 'selectWorkspace', workspace })}
          close={() => setWorkspaceOpen(false)}
          fallbackFocus={() =>
            mobile ? menuRef.current : document.querySelector<HTMLElement>('[data-wb-focus="workspace-picker"]')
          }
        />
      )}
      <IconTooltips navigationKey={`${routeIdentity(state.route)}:${props.locale}:${workspaceOpen}`} />
      {mobile && menuOpen && (
        <button
          type="button"
          className="wb-sidebar-scrim"
          aria-label={t('wbMenuClose')}
          onClick={() => closeMenu(true)}
          tabIndex={-1}
        />
      )}
    </div>
  );
}

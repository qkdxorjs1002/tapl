import type {
  DisplayLayout,
  HostMessage,
  WebviewCommand,
  WebviewView
} from './types';

type VsCodeApi = {
  postMessage: (message: WebviewCommand) => void;
  getState: () => unknown;
  setState: (state: unknown) => void;
};

type PersistedState = {
  view?: WebviewView;
  locale?: 'en' | 'ko';
  layout?: DisplayLayout;
};

declare const acquireVsCodeApi: (() => VsCodeApi) | undefined;

const SESSION_STATE_KEY = 'tapl.viewer.state.v1';
const SESSION_HISTORY_KEY = 'tapl.viewer.history.v1';
const WORKSPACE_KEY = 'tapl.viewer.workspace.v1';

let api: VsCodeApi | undefined;

export function vscodeApi(): VsCodeApi {
  if (!api) {
    api = typeof acquireVsCodeApi === 'function'
      ? acquireVsCodeApi()
      : new BrowserApi();
  }
  return api;
}

class BrowserApi implements VsCodeApi {
  private state = readStorage<PersistedState>(sessionStorage, SESSION_STATE_KEY) ?? {};
  private history = readStorage<WebviewView[]>(sessionStorage, SESSION_HISTORY_KEY) ?? [];
  private activeWorkspace: string | undefined;

  postMessage(message: WebviewCommand): void {
    if (message.command === 'back') {
      this.goBack();
      return;
    }
    if (message.command === 'chooseWorkspace') {
      this.showWorkspaceChooser();
      return;
    }
    void this.send(message);
  }

  getState(): unknown {
    return this.state;
  }

  setState(state: unknown): void {
    this.state = isRecord(state) ? state as PersistedState : {};
    writeStorage(sessionStorage, SESSION_STATE_KEY, this.state);
  }

  private async send(message: Exclude<WebviewCommand, { command: 'back' | 'chooseWorkspace' }>): Promise<void> {
    const previous = this.state.view;
    const recentWorkspace = readStorage<string>(localStorage, WORKSPACE_KEY) ?? '';
    const requestWorkspace = message.command === 'ready'
      ? ''
      : message.command === 'selectWorkspace'
        ? message.workspace.trim()
        : this.activeWorkspace ?? recentWorkspace;
    const request = {
      ...message,
      workspace: requestWorkspace,
      locale: navigator.language,
      layout: this.state.layout ?? 'auto',
      ...refreshContext(message, previous)
    };

    try {
      const response = await fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request)
      });
      const payload = await response.json() as HostMessage;
      if (!response.ok) {
        throw new Error(isRecord(payload) && typeof payload.message === 'string'
          ? payload.message
          : `Viewer request failed (${response.status}).`);
      }
      if ((payload.type === 'hydrate' || payload.type === 'view:update') && 'workspace' in payload) {
        this.activeWorkspace = payload.workspace ?? '';
        if (payload.workspace) {
          writeStorage(localStorage, WORKSPACE_KEY, payload.workspace);
        }
      }
      if (
        message.command === 'ready'
        && (payload.type === 'hydrate' || payload.type === 'view:update')
        && payload.view.type === 'workspace'
        && recentWorkspace
      ) {
        await this.send({ command: 'selectWorkspace', workspace: recentWorkspace });
        return;
      }
      if (shouldPushHistory(message, previous, payload)) {
        this.history.push(previous as WebviewView);
        this.persistHistory();
      }
      dispatchHostMessage(payload);
    } catch (error) {
      dispatchHostMessage({
        type: 'error',
        message: error instanceof Error ? error.message : 'The local viewer request failed.',
        locale: this.state.locale ?? resolveBrowserLocale(),
        layout: this.state.layout ?? 'auto'
      });
    }
  }

  private goBack(): void {
    const previous = this.history.pop();
    this.persistHistory();
    if (!previous) {
      void this.send({ command: 'ready' });
      return;
    }
    dispatchHostMessage({
      type: 'view:update',
      view: previous,
      locale: this.state.locale ?? resolveBrowserLocale(),
      layout: this.state.layout ?? 'auto'
    });
  }

  private showWorkspaceChooser(): void {
    if (this.state.view && this.state.view.type !== 'workspace') {
      this.history.push(this.state.view);
      this.persistHistory();
    }
    dispatchHostMessage({
      type: 'view:update',
      view: {
        type: 'workspace',
        workspace: readStorage<string>(localStorage, WORKSPACE_KEY) ?? '',
        message: ''
      },
      locale: this.state.locale ?? resolveBrowserLocale(),
      layout: this.state.layout ?? 'auto'
    });
  }

  private persistHistory(): void {
    writeStorage(sessionStorage, SESSION_HISTORY_KEY, this.history.slice(-20));
  }
}

function refreshContext(
  message: Exclude<WebviewCommand, { command: 'back' | 'chooseWorkspace' }>,
  view: WebviewView | undefined
): Record<string, unknown> {
  if (message.command !== 'refresh' || !view) {
    return {};
  }
  if (view.type === 'archive' || view.type === 'archiveEvents') {
    return { viewType: view.type, archiveId: view.archive.id };
  }
  if (view.type === 'search') {
    return { viewType: view.type, query: view.search.query };
  }
  if (view.type === 'searchItem') {
    return { viewType: view.type, itemId: view.result.id };
  }
  return { viewType: view.type };
}

function shouldPushHistory(
  command: Exclude<WebviewCommand, { command: 'back' | 'chooseWorkspace' }>,
  previous: WebviewView | undefined,
  response: HostMessage
): boolean {
  if (!previous || command.command === 'ready' || command.command === 'refresh' || command.command === 'selectWorkspace') {
    return false;
  }
  return (response.type === 'hydrate' || response.type === 'view:update')
    && response.view.type !== 'error'
    && response.view.type !== 'workspace';
}

function resolveBrowserLocale(): 'en' | 'ko' {
  return navigator.language.toLowerCase().startsWith('ko') ? 'ko' : 'en';
}

function dispatchHostMessage(message: HostMessage): void {
  window.dispatchEvent(new MessageEvent('message', { data: message }));
}

function readStorage<T>(storage: Storage, key: string): T | undefined {
  try {
    const value = storage.getItem(key);
    return value ? JSON.parse(value) as T : undefined;
  } catch {
    return undefined;
  }
}

function writeStorage(storage: Storage, key: string, value: unknown): void {
  try {
    storage.setItem(key, JSON.stringify(value));
  } catch {
    // Private browsing or storage policy can disable persistence; the viewer still works.
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

import type { HostCapabilities, ViewerPreferences, WebviewView } from './types';
import type { SupportedLocale } from '../i18n';

export interface PersistedAppState {
  view?: WebviewView;
  locale?: SupportedLocale;
  preferences?: ViewerPreferences;
  layout?: unknown;
  capabilities?: HostCapabilities;
  workspace?: string;
  workbench?: unknown;
  workbenchWorkspace?: string;
}

/** Native state is serialized across the VS Code bridge, so retain UI restoration only. */
export function mergePersistedAppState(previous: unknown, values: Partial<PersistedAppState>, browser: boolean): PersistedAppState {
  const current = previous && typeof previous === 'object' ? previous as Record<string, unknown> : {};
  const merged: Record<string, unknown> = { ...current, ...values };
  if (browser) {
    const { userLocale: _userLocale, hostLocale: _hostLocale, ...state } = merged;
    return state;
  }
  const state: Record<string, unknown> = {};
  for (const key of ['preferences', 'locale', 'layout', 'workspace', 'workbench', 'workbenchWorkspace']) {
    if (merged[key] !== undefined) state[key] = merged[key];
  }
  return state;
}

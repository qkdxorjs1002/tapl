import { readFileSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { isAbsolute, join } from 'node:path';
import type { ViewerPreferences } from './viewer/types';

// smol-toml 1.x ships ESM declarations for both runtime exports. Use its
// CommonJS entry point explicitly in this CommonJS extension host.
declare const require: (name: 'smol-toml') => {
  parse(text: string, options: { integersAsBigInt: 'asNeeded' }): Record<string, unknown>;
};
const { parse } = require('smol-toml');

export interface ViewerConfig {
  path: string;
  exists: boolean;
  scope: 'workspace' | 'user';
  preferences: ViewerPreferences;
}

export function defaultViewerPreferences(): ViewerPreferences {
  return { language: 'auto', layout: 'auto', mcp_path: '' };
}

/** Relative commands resolve in the selected workspace even when stored in user config. */
export function viewerConfigRequiresTrust(config: ViewerConfig): boolean {
  const command = config.preferences.mcp_path;
  return command !== '' && (config.scope === 'workspace' || !isAbsolute(command));
}

/** Read before starting MCP: a configured executable cannot depend on that server. */
export function loadViewerConfig(
  workspacePath?: string,
  options: { homeDir?: string } = {}
): ViewerConfig {
  const userPath = join(options.homeDir ?? homedir(), '.tapl', 'config.toml');
  const localPath = workspacePath ? join(workspacePath, '.tapl', 'config.toml') : userPath;
  let path = localPath;
  let scope: ViewerConfig['scope'] = workspacePath ? 'workspace' : 'user';
  try {
    let exists = fileExists(localPath);
    if (!exists && localPath !== userPath && fileExists(userPath)) {
      path = userPath;
      scope = 'user';
      exists = true;
    }
    if (!exists) return { path, scope, exists: false, preferences: defaultViewerPreferences() };
    // Parse the entire selected TOML document, but validate only the bootstrap fields.
    const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(readFileSync(path));
    const data = parse(text, { integersAsBigInt: 'asNeeded' });
    const viewer = Object.prototype.hasOwnProperty.call(data, 'viewer') ? data.viewer : {};
    if (typeof viewer !== 'object' || viewer === null || Array.isArray(viewer) || viewer instanceof Date) {
      throw new Error('viewer must be a TOML table');
    }
    const values = viewer as Record<string, unknown>;
    const language = choice(values, 'language', ['auto', 'ko', 'en'] as const);
    const layout = choice(values, 'layout', ['auto', 'small', 'medium', 'large'] as const);
    const mcpPath = Object.prototype.hasOwnProperty.call(values, 'mcp_path') ? values.mcp_path : '';
    if (typeof mcpPath !== 'string') throw new Error('viewer.mcp_path must be a string');
    if (/[\u0000-\u001f\u007f-\u009f]/u.test(mcpPath)) {
      throw new Error('viewer.mcp_path must not contain control characters');
    }
    return { path, scope, exists: true, preferences: { language, layout, mcp_path: mcpPath } };
  } catch (error) {
    throw new Error(`Unable to read TAPL configuration ${path}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function fileExists(path: string): boolean {
  try {
    statSync(path);
    return true;
  } catch (error) {
    if ((error as { code?: string }).code === 'ENOENT' || (error as { code?: string }).code === 'ENOTDIR') return false;
    throw error;
  }
}

function choice<T extends string>(values: Record<string, unknown>, key: string, allowed: readonly T[]): T {
  const value = Object.prototype.hasOwnProperty.call(values, key) ? values[key] : 'auto';
  if (typeof value !== 'string') throw new Error(`viewer.${key} must be a string`);
  const normalized = value.trim().toLowerCase().replace(/-/g, '_') as T;
  if (!allowed.includes(normalized)) throw new Error(`viewer.${key} must be one of: ${allowed.join(', ')}`);
  return normalized;
}

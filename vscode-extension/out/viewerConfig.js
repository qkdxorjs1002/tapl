"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.defaultViewerPreferences = defaultViewerPreferences;
exports.viewerConfigRequiresTrust = viewerConfigRequiresTrust;
exports.loadViewerConfig = loadViewerConfig;
const node_fs_1 = require("node:fs");
const node_os_1 = require("node:os");
const node_path_1 = require("node:path");
const { parse } = require('smol-toml');
function defaultViewerPreferences() {
    return { language: 'auto', layout: 'auto', mcp_path: '' };
}
/** Relative commands resolve in the selected workspace even when stored in user config. */
function viewerConfigRequiresTrust(config) {
    const command = config.preferences.mcp_path;
    return command !== '' && (config.scope === 'workspace' || !(0, node_path_1.isAbsolute)(command));
}
/** Read before starting MCP: a configured executable cannot depend on that server. */
function loadViewerConfig(workspacePath, options = {}) {
    const userPath = (0, node_path_1.join)(options.homeDir ?? (0, node_os_1.homedir)(), '.tapl', 'config.toml');
    const localPath = workspacePath ? (0, node_path_1.join)(workspacePath, '.tapl', 'config.toml') : userPath;
    let path = localPath;
    let scope = workspacePath ? 'workspace' : 'user';
    try {
        let exists = fileExists(localPath);
        if (!exists && localPath !== userPath && fileExists(userPath)) {
            path = userPath;
            scope = 'user';
            exists = true;
        }
        if (!exists)
            return { path, scope, exists: false, preferences: defaultViewerPreferences() };
        // Parse the entire selected TOML document, but validate only the bootstrap fields.
        const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode((0, node_fs_1.readFileSync)(path));
        const data = parse(text, { integersAsBigInt: 'asNeeded' });
        const viewer = Object.prototype.hasOwnProperty.call(data, 'viewer') ? data.viewer : {};
        if (typeof viewer !== 'object' || viewer === null || Array.isArray(viewer) || viewer instanceof Date) {
            throw new Error('viewer must be a TOML table');
        }
        const values = viewer;
        const language = choice(values, 'language', ['auto', 'ko', 'en']);
        const layout = choice(values, 'layout', ['auto', 'small', 'medium', 'large']);
        const mcpPath = Object.prototype.hasOwnProperty.call(values, 'mcp_path') ? values.mcp_path : '';
        if (typeof mcpPath !== 'string')
            throw new Error('viewer.mcp_path must be a string');
        if (/[\u0000-\u001f\u007f-\u009f]/u.test(mcpPath)) {
            throw new Error('viewer.mcp_path must not contain control characters');
        }
        return { path, scope, exists: true, preferences: { language, layout, mcp_path: mcpPath } };
    }
    catch (error) {
        throw new Error(`Unable to read TAPL configuration ${path}: ${error instanceof Error ? error.message : String(error)}`);
    }
}
function fileExists(path) {
    try {
        (0, node_fs_1.statSync)(path);
        return true;
    }
    catch (error) {
        if (error.code === 'ENOENT' || error.code === 'ENOTDIR')
            return false;
        throw error;
    }
}
function choice(values, key, allowed) {
    const value = Object.prototype.hasOwnProperty.call(values, key) ? values[key] : 'auto';
    if (typeof value !== 'string')
        throw new Error(`viewer.${key} must be a string`);
    const normalized = value.trim().toLowerCase().replace(/-/g, '_');
    if (!allowed.includes(normalized))
        throw new Error(`viewer.${key} must be one of: ${allowed.join(', ')}`);
    return normalized;
}
//# sourceMappingURL=viewerConfig.js.map
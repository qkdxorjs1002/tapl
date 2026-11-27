"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.installedViewerBundle = installedViewerBundle;
const promises_1 = require("node:fs/promises");
const node_path_1 = require("node:path");
const types_1 = require("./viewer/types");
/** Only the selected Viewer MCP process can advertise its own package resources. */
async function installedViewerBundle(clients, workspace) {
    if (!await clients.supportsTool(workspace, 'tapl_viewer_get_bundle')
        || !await clients.supportsTool(workspace, 'tapl_viewer_dispatch'))
        return;
    const bundle = await clients.callTool(workspace, 'tapl_viewer_get_bundle', {});
    if (bundle.ok !== true || bundle.protocol !== types_1.INSTALLED_VIEWER_PROTOCOL
        || typeof bundle.ctl_version !== 'string' || !bundle.ctl_version
        || typeof bundle.asset_root !== 'string' || !(0, node_path_1.isAbsolute)(bundle.asset_root)
        || (0, node_path_1.basename)(bundle.asset_root) !== '_viewer' || (0, node_path_1.basename)((0, node_path_1.dirname)(bundle.asset_root)) !== 'taplctl')
        return;
    const root = await (0, promises_1.realpath)(bundle.asset_root);
    if ((0, node_path_1.basename)(root) !== '_viewer' || (0, node_path_1.basename)((0, node_path_1.dirname)(root)) !== 'taplctl'
        || !(await (0, promises_1.lstat)(bundle.asset_root)).isDirectory())
        return;
    const assets = (0, node_path_1.join)(root, 'assets');
    const [directory, script, style] = await Promise.all([
        (0, promises_1.lstat)(assets), (0, promises_1.lstat)((0, node_path_1.join)(assets, 'index.js')), (0, promises_1.lstat)((0, node_path_1.join)(assets, 'index.css'))
    ]);
    if (directory.isDirectory() && script.isFile() && style.isFile())
        return { assets, version: bundle.ctl_version };
}
//# sourceMappingURL=viewerInstall.js.map
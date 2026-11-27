import { lstat, realpath } from 'node:fs/promises';
import { basename, dirname, isAbsolute, join } from 'node:path';
import type { TaplMcpClientPool, TaplMcpWorkspace } from './taplMcpClient';
import { INSTALLED_VIEWER_PROTOCOL } from './viewer/types';

export interface InstalledViewerBundle {
  assets: string;
  version: string;
}

/** Only the selected Viewer MCP process can advertise its own package resources. */
export async function installedViewerBundle(clients: TaplMcpClientPool, workspace: TaplMcpWorkspace): Promise<InstalledViewerBundle | undefined> {
  if (!await clients.supportsTool(workspace, 'tapl_viewer_get_bundle')
    || !await clients.supportsTool(workspace, 'tapl_viewer_dispatch')) return;
  const bundle = await clients.callTool(workspace, 'tapl_viewer_get_bundle', {});
  if (bundle.ok !== true || bundle.protocol !== INSTALLED_VIEWER_PROTOCOL
    || typeof bundle.ctl_version !== 'string' || !bundle.ctl_version
    || typeof bundle.asset_root !== 'string' || !isAbsolute(bundle.asset_root)
    || basename(bundle.asset_root) !== '_viewer' || basename(dirname(bundle.asset_root)) !== 'taplctl') return;

  const root = await realpath(bundle.asset_root);
  if (basename(root) !== '_viewer' || basename(dirname(root)) !== 'taplctl'
    || !(await lstat(bundle.asset_root)).isDirectory()) return;
  const assets = join(root, 'assets');
  const [directory, script, style] = await Promise.all([
    lstat(assets), lstat(join(assets, 'index.js')), lstat(join(assets, 'index.css'))
  ]);
  if (directory.isDirectory() && script.isFile() && style.isFile()) return { assets, version: bundle.ctl_version };
}

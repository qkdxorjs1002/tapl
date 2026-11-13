import { readdir, stat as fileStat } from 'node:fs/promises';
import { join } from 'node:path';

// SQLite opens and removes SHM and empty WAL files even for reads. Only database
// files and WALs with frames represent a possible committed data change.
export async function databaseRevision(workspace: string): Promise<string | undefined> {
  try {
    const directory = join(workspace, '.tapl');
    let names: string[];
    try { names = await readdir(directory); }
    catch (error) {
      if ((error as { code?: string }).code === 'ENOENT') { return '[]'; }
      throw error;
    }
    const entries: string[] = [];
    for (const name of names.sort()) {
      if (!/^tapl(?:-.+)?\.db(?:-wal)?$/.test(name)) { continue; }
      let stat;
      try { stat = await fileStat(join(directory, name), { bigint: true }); }
      catch (error) {
        // An ephemeral sidecar may disappear between readdir and stat.
        if (name.endsWith('-wal') && (error as { code?: string }).code === 'ENOENT') { continue; }
        throw error;
      }
      if (!stat.isFile() || (name.endsWith('-wal') && stat.size <= 32n)) { continue; }
      entries.push(`${name}:${stat.ino}:${stat.size}:${stat.mtimeNs}:${stat.ctimeNs}`);
    }
    return JSON.stringify(entries);
  } catch { return undefined; }
}

export class DatabaseRevisions {
  private readonly accepted = new Map<string, string>();
  private readonly observations = new Map<string, number>();

  constructor(private readonly capture: (workspace: string) => string | undefined | Promise<string | undefined> = databaseRevision) {}

  async read(workspace: string): Promise<string | undefined> { return this.capture(workspace); }

  changed(workspace: string, revision: string | undefined): boolean {
    return revision === undefined || this.accepted.get(workspace) !== revision;
  }

  // This cursor belongs to the whole refresh round, not one panel or tree read.
  // Advancing it when just one consumer reads would hide changes from the others.
  accept(workspace: string, revision: string | undefined): void {
    if (revision === undefined) { this.accepted.delete(workspace); }
    else { this.accepted.set(workspace, revision); }
  }

  // A snapshot detects concurrent changes but never consumes another view's signal.
  async observe(workspace: string, before: string | undefined, valid: boolean | (() => boolean)): Promise<boolean> {
    const current = () => typeof valid === 'function' ? valid() : valid;
    if (!current()) { return true; }
    const observation = (this.observations.get(workspace) ?? 0) + 1;
    this.observations.set(workspace, observation);
    const after = await this.capture(workspace);
    if (!current() || this.observations.get(workspace) !== observation) { return true; }
    if (before === undefined || after === undefined) { return true; }
    if (before !== after) { return false; }
    return true;
  }
}

export class ViewerRefreshQueue {
  private timer: ReturnType<typeof setTimeout> | undefined;
  private running: Promise<void> | undefined;
  private dirty = false;
  private force = false;
  private scheduledForce = false;
  private disposed = false;

  constructor(
    private readonly currentWorkspace: () => string | undefined,
    private readonly revisions: DatabaseRevisions,
    private readonly refresh: () => Promise<void>,
    private readonly delayMs: number
  ) {}

  schedule(workspace = this.currentWorkspace(), force = false): void {
    if (this.disposed || workspace !== this.currentWorkspace()) { return; }
    // Automatic changes keep the trailing debounce even during a snapshot.
    // Otherwise continuous commits can turn the single-flight queue into a hot loop.
    this.scheduledForce ||= force;
    if (this.timer !== undefined) { clearTimeout(this.timer); }
    this.timer = setTimeout(() => {
      this.timer = undefined;
      const force = this.scheduledForce;
      this.scheduledForce = false;
      if (workspace === this.currentWorkspace()) { void this.request(force); }
    }, this.delayMs);
  }

  request(force = false): Promise<void> {
    if (this.disposed) { return Promise.resolve(); }
    if (this.timer !== undefined) { clearTimeout(this.timer); this.timer = undefined; }
    this.dirty = true;
    this.force ||= force || this.scheduledForce;
    this.scheduledForce = false;
    if (!this.running) {
      this.running = Promise.resolve().then(() => this.drain()).finally(() => {
        this.running = undefined;
        if (this.dirty && !this.disposed) { void this.request(); }
      });
    }
    return this.running;
  }

  private async drain(): Promise<void> {
    while (this.dirty && !this.disposed) {
      this.dirty = false;
      const force = this.force;
      this.force = false;
      const workspace = this.currentWorkspace();
      const revision = workspace ? await this.revisions.read(workspace) : undefined;
      if (this.disposed) { return; }
      if (workspace !== this.currentWorkspace()) {
        this.force ||= force;
        this.dirty = true;
        continue;
      }
      if (force || (workspace && this.revisions.changed(workspace, revision))) {
        if (workspace) { this.revisions.accept(workspace, revision); }
        await this.refresh();
      }
    }
  }

  dispose(): void {
    this.disposed = true;
    if (this.timer !== undefined) { clearTimeout(this.timer); this.timer = undefined; }
  }
}

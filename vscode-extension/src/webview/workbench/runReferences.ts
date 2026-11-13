import type { TaplRunReference, TaplRunSnapshot, WebviewCommand } from '../types';

/** Database identity is part of every key, even when IDs happen to match. */
export function runReferenceKey(reference: TaplRunReference): string {
  return JSON.stringify(['reference', reference.kind, reference.source_db, reference.target_type,
    reference.target_type === 'memory' ? reference.memory_id : reference.target_type === 'item' ? reference.item_id : reference.run_id]);
}

export function runReferenceCommand(reference: TaplRunReference): WebviewCommand | undefined {
  const source_db = reference.source_db;
  if (reference.target_type === 'memory' && reference.memory_id) return { command: 'openMemory', memoryId: reference.memory_id, source_db };
  if (reference.target_type === 'item' && typeof reference.item_id === 'number' && Number.isFinite(reference.item_id)) {
    return { command: 'openSearchResult', itemId: reference.item_id, source_db };
  }
  if (reference.target_type === 'run' && reference.run_id) return { command: 'openRun', runId: reference.run_id, source_db };
  return undefined;
}

/** A later retrieved result cannot demote an original that was already opened. */
export function runMindmapReferences(snapshot: TaplRunSnapshot): TaplRunReference[] {
  const references = new Map<string, TaplRunReference>();
  for (const reference of snapshot.references ?? []) {
    if (!runReferenceCommand(reference)) continue;
    if (reference.kind === 'history' && reference.source_db === (snapshot.run.source_db ?? '') && reference.run_id === snapshot.run.id) continue;
    const key = runReferenceKey(reference), previous = references.get(key);
    if (previous?.stage === 'opened' && reference.stage !== 'opened') continue;
    references.set(key, reference);
  }
  return [...references.values()].sort((a, b) => runReferenceKey(a).localeCompare(runReferenceKey(b)));
}

/** Cached cards keep identities; click handlers resolve the current host payload. */
export function latestRunReference(snapshot: TaplRunSnapshot, reference: TaplRunReference): TaplRunReference | undefined {
  const key = runReferenceKey(reference);
  return runMindmapReferences(snapshot).find(candidate => runReferenceKey(candidate) === key);
}

export function memoryReferencesHistory(memory: TaplRunReference, history: TaplRunReference): boolean {
  if (memory.kind !== 'memory' || history.kind !== 'history' || history.stage !== 'opened') return false;
  const key = referenceOriginalKey(memory);
  return key !== undefined && key === referenceOriginalKey(history);
}

/** Item pointers never broaden to their RUN. Archive pointers retain exact RUN identity. */
export function referenceOriginalKey(reference: TaplRunReference): string | undefined {
  if (reference.kind === 'memory') {
    const source = reference.source;
    return source && JSON.stringify([source.source_db, source.run_id, source.item_id ?? null]);
  }
  if (reference.target_type === 'item' || reference.target_type === 'run') {
    return JSON.stringify([reference.source_db, reference.run_id, reference.target_type === 'item' ? reference.item_id : null]);
  }
  return undefined;
}

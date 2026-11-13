import type { AssociativeMemory, TaplItem, TaplRunSnapshot } from '../types';
import { runMindmapReferences } from './runReferences';

/** Only inputs consumed by RUN layout, cards, relationships and follow state belong here. */
export function runMindmapProjection(snapshot: TaplRunSnapshot): unknown {
  const item = ({ id, stable_id, kind, title, status, source_db, run_id, spec_id }: TaplItem) =>
    [id, stable_id, kind, title, status, source_db, run_id, spec_id];
  const { id, source_db, status, request_summary, slug } = snapshot.run;
  const references = runMindmapReferences(snapshot).map(({kind, stage, source_db, target_type, run_id, title, memory_id, item_id, stable_id, record_kind, source}) =>
    [kind, stage, source_db, target_type, run_id, title, memory_id, item_id, stable_id, record_kind, source && [source.source_db, source.run_id, source.item_id]]);
  return [[id, source_db, status, request_summary, slug], snapshot.plans.map(item), snapshot.tasks.map(item), references];
}

/** Strength decay and full source records do not change memory cards or their relationships. */
export function memoryMindmapProjection(memories: AssociativeMemory[]): unknown {
  return memories.map(({ id, source_db, note, cue, state, revision, source, matched_cues, source_available }) =>
    [id, source_db, note, cue, state, revision, source && [source.kind, source.run_id, source.item_id, source.title], matched_cues, source_available]);
}

/** Resolve navigation against current records; cached graph records are layout identities only. */
export function latestMindmapItem(snapshot: TaplRunSnapshot, item: TaplItem): TaplItem | undefined {
  const source = item.source_db ?? snapshot.run.source_db;
  const run = item.run_id ?? snapshot.run.id;
  return [...snapshot.plans, ...snapshot.tasks].find((candidate) =>
    candidate.id === item.id && candidate.stable_id === item.stable_id && candidate.kind === item.kind &&
    (candidate.source_db ?? snapshot.run.source_db) === source && (candidate.run_id ?? snapshot.run.id) === run);
}

/** Equality for immutable JSON-shaped host data; record bodies remain part of the comparison. */
export function sameMindmapValue(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((value, index) => sameMindmapValue(value, b[index]));
  }
  const left = a as Record<string, unknown>, right = b as Record<string, unknown>;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every((key) => Object.prototype.hasOwnProperty.call(right, key) && sameMindmapValue(left[key], right[key]));
}

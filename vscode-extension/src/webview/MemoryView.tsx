import { FormEvent, useEffect, useRef, useState } from 'react';
import type { AssociativeMemory, WebviewCommand, WebviewView } from './types';
import { useI18n } from './i18n';

type MemoryScreen = Extract<WebviewView, { type: 'memories' | 'memory' | 'memorySource' }>;
type Send = (message: WebviewCommand) => void;

export function MemoryView({ view, supported, send }: { view: MemoryScreen; supported: boolean; send: Send }): JSX.Element {
  const { t } = useI18n();
  const heading = useRef<HTMLHeadingElement>(null);
  const identity = view.type === 'memories' ? `memories:${view.query}:${view.offset}` : `${view.type}:${view.memoryId}`;
  useEffect(() => { heading.current?.focus(); }, [identity]);
  return <>
    <header className="tapl-topbar tapl-memory-header">
      <div>
        <span className="tapl-eyebrow">{t('memories')}</span>
        <h1 ref={heading} tabIndex={-1} className="m-0 text-2xl font-semibold">{t(view.type === 'memories' ? 'memories' : view.type === 'memory' ? 'memoryDetail' : 'memoryRunSource')}</h1>
        <p className="tapl-muted m-0">{t('memoryReadOnly')}</p>
      </div>
      <div className="tapl-command-actions">
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => send({ command: 'back' })}>{t('back')}</button>
        {supported && <button type="button" className="btn btn-primary btn-sm" onClick={() => send({ command: 'refresh' })}>{t('refresh')}</button>}
      </div>
    </header>
    {!supported ? <p role="status" className="tapl-memory-empty">{t('memoryUnsupported')}</p>
      : view.type === 'memories' ? <MemoryList view={view} send={send} />
      : view.type === 'memory' ? (view.memory && view.memory.state !== 'deleted' ? <MemoryDetail memory={view.memory} send={send} /> : <p role="status" className="tapl-memory-empty">{t('memoryUnavailable')}</p>)
      : <section className="tapl-card"><div className="tapl-card-body tapl-memory-detail">
        <h2 className="m-0 text-xl font-semibold">{view.run.slug || view.run.id}</h2>
        <h3>{t('request')}</h3><p className="tapl-memory-note">{view.run.request_summary || t('notRecorded')}</p>
        <h3>{t('result')}</h3><p className="tapl-memory-note">{view.run.result_summary || t('notRecorded')}</p>
      </div></section>}
  </>;
}

function MemoryList({ view, send }: { view: Extract<WebviewView, { type: 'memories' }>; send: Send }): JSX.Element {
  const { t } = useI18n();
  const [query, setQuery] = useState(view.query);
  useEffect(() => { setQuery(view.query); }, [view.query]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    send({ command: 'memories', query: query.trim(), offset: 0 });
  };
  const limit = Math.max(1, view.limit || 20);
  return <section className="tapl-card" aria-label={t('memories')}>
    <div className="tapl-card-body tapl-memory-detail">
      <p className="tapl-muted m-0">{t('memoryIntro')}</p>
      <form className="tapl-memory-search" role="search" aria-label={t('searchMemories')} onSubmit={submit}>
        <label htmlFor="memory-query">{t('searchMemories')}</label>
        <div><input id="memory-query" type="search" className="input input-bordered" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('searchMemories')} />
          <button className="btn btn-primary" type="submit">{t('search')}</button></div>
      </form>
      <p className="tapl-muted text-sm m-0" role="status">{t('memoryRange', { start: view.memories.length ? view.offset + 1 : 0, end: view.offset + view.memories.length, total: view.total })}</p>
      {view.memories.length ? <ul className="tapl-memory-list">{view.memories.map((memory) => <li key={memory.id} className="tapl-memory-row">
        <button type="button" className="tapl-memory-open" onClick={() => send({ command: 'openMemory', memoryId: memory.id })}>
          <span className="tapl-memory-preview">{memory.note}</span>
          <span className="tapl-memory-source-title">{memory.source.title || memory.source.run_id}</span>
        </button>
        <Cues memory={memory} />
        <MemoryUse memory={memory} compact />
      </li>)}</ul> : <p className="tapl-memory-empty">{t(view.query ? 'noMemoryMatches' : 'noMemories')}</p>}
      <nav className="tapl-memory-pagination" aria-label={t('memories')}>
        <button className="btn btn-secondary btn-sm" type="button" disabled={view.offset === 0} onClick={() => send({ command: 'memories', query: view.query, offset: Math.max(0, view.offset - limit) })}>{t('previousPage')}</button>
        <button className="btn btn-secondary btn-sm" type="button" disabled={view.offset + view.memories.length >= view.total} onClick={() => send({ command: 'memories', query: view.query, offset: view.offset + limit })}>{t('nextPage')}</button>
      </nav>
    </div>
  </section>;
}

function Cues({ memory }: { memory: AssociativeMemory }): JSX.Element {
  const { t } = useI18n();
  return <div className="tapl-memory-cues" aria-label={t('memoryCues')}>{memory.cue.map((cue) => <span key={cue} className={`tapl-memory-cue${memory.matched_cues.includes(cue) ? ' is-matched' : ''}`} title={memory.matched_cues.includes(cue) ? t('matchedCues') : undefined}>{cue}</span>)}</div>;
}

function MemoryUse({ memory, compact = false }: { memory: AssociativeMemory; compact?: boolean }): JSX.Element {
  const { t, locale } = useI18n();
  const ease = memory.strength >= 0.67 ? 'recallEasy' : memory.strength >= 0.33 ? 'recallModerate' : 'recallFaint';
  return <dl className={`tapl-memory-facts${compact ? ' is-compact' : ''}`}>
    <div><dt>{t('recallEase')}</dt><dd title={t('recallHelp')} className={`tapl-memory-strength ${ease}`}>{t(ease)}</dd></div>
    <div><dt>{t('lastMemoryUse')}</dt><dd>{memory.last_reinforced_at ? <time dateTime={memory.last_reinforced_at}>{formatTime(memory.last_reinforced_at, locale)}</time> : t('memoryNeverUsed')}</dd></div>
  </dl>;
}

function MemoryDetail({ memory, send }: { memory: AssociativeMemory; send: Send }): JSX.Element {
  const { t, locale } = useI18n();
  return <section className="tapl-card"><div className="tapl-card-body tapl-memory-detail">
    <div className="tapl-memory-state">{t(memory.state === 'active' ? 'memoryActive' : memory.state === 'superseded' ? 'memorySuperseded' : 'memoryDeleted')}</div>
    <p className="tapl-memory-note">{memory.note}</p>
    <Cues memory={memory} />
    <MemoryUse memory={memory} />
    <p className="tapl-muted text-sm m-0">{t('recallHelp')}</p>
    <dl className="tapl-memory-facts">
      <div><dt>{t('created')}</dt><dd><time dateTime={memory.created_at}>{formatTime(memory.created_at, locale)}</time></dd></div>
      <div><dt>{t('memoryContentUpdated')}</dt><dd><time dateTime={memory.updated_at}>{formatTime(memory.updated_at, locale)}</time></dd></div>
    </dl>
    <div className="tapl-memory-origin">
      <span className="tapl-eyebrow">{t('originalSource')}</span>
      <p className="m-0">{memory.source.title || memory.source.run_id}</p>
      {memory.source_available ? <button className="btn btn-secondary btn-sm" type="button" onClick={() => send({ command: 'openMemorySource', memoryId: memory.id })}>{t('openOriginalSource')}</button> : <p className="tapl-muted m-0">{t('sourceUnavailable')}</p>}
    </div>
  </div></section>;
}

function formatTime(value: string, locale: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale);
}

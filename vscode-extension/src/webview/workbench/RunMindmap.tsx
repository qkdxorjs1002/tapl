import { memo, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { useI18n } from '../i18n';
import type { TaplItem, TaplRunSnapshot, TaplWorkflowRun } from '../types';
import { Icon } from './Icon';
import { buildRunMindmap, type MindmapNode } from './mindmap';
import { useMindmapViewport } from './mindmapViewport';
import { mindmapRunActiveKeys, mindmapRunFollowKeys } from './mindmapCamera';
import { MindmapEdge } from './MindmapEdges';
import { buildMindmapRelationIndex, relatedMindmapNodes } from './mindmapRelations';
import { useMindmapAction, useMindmapValue } from './useMindmapCache';
import './run-mindmap.css';

const openable = (item?: TaplItem) => typeof item?.id === 'number' && Number.isFinite(item.id);
const stateKind = (value?: string) =>
  value === 'In Progress' || value === 'active'
    ? 'progress'
    : value === 'Completed' || value === 'Finalized' || value === 'completed'
      ? 'completed'
      : value === 'Blocked' || value === 'blocked'
        ? 'blocked'
        : 'pending';

/** A RUN-owned camera survives record details and source-safe RUN navigation. */
export function RunMindmap({
  snapshot: incomingSnapshot,
  open: incomingOpen,
  back
}: {
  snapshot: TaplRunSnapshot;
  open: (item: TaplItem, run?: TaplWorkflowRun) => void;
  back?: () => void;
}): JSX.Element {
  const { t, status } = useI18n();
  const snapshot = useMindmapValue(incomingSnapshot);
  const open = useMindmapAction(incomingOpen);
  const graph = useMemo(() => buildRunMindmap(snapshot), [snapshot]);
  const runKey = JSON.stringify([snapshot.run.source_db ?? '', snapshot.run.id]);
  const follow = useMemo(() => mindmapRunFollowKeys(graph.nodes, snapshot.run.status), [graph, snapshot.run.status]);
  const [active, setActive] = useState<string>();
  const relations = useMemo(() => buildMindmapRelationIndex(graph, 'node-parent'), [graph]);
  const { hostRef, worldRef, controlsRef, edges, suppressClickCapture, following } = useMindmapViewport({
    graph,
    cameraKey: runKey,
    follow,
    setActive
  });
  const executing = useMemo(() => mindmapRunActiveKeys(graph.nodes, snapshot.run.status), [graph, snapshot.run.status]);
  const related = useMemo(() => {
    if (active && relations.keys.has(active)) return relatedMindmapNodes(relations, active);
    return following ? relatedMindmapNodes(relations, executing, { ancestorsOnly: true }) : undefined;
  }, [active, relations, following, executing]);

  return (
    <div
      className="wb-mindmap wb-run-mindmap"
      ref={hostRef}
      role="region"
      tabIndex={0}
      aria-label={t('wbMindmap')}
      aria-description={t('wbMindmapHelp')}
      data-wb-page-heading
      data-run-key={runKey}
      onClickCapture={suppressClickCapture}
    >
      <div className="wb-mm-pointer-light" aria-hidden="true" />
      <div className="wb-mm-world" ref={worldRef}>
        <svg className="wb-mm-connections" aria-hidden="true">
          {edges.map((edge) => (
            <MindmapEdge
              key={`${edge.from}:${edge.to}`}
              edge={edge}
              emphasis={related ? (related.has(edge.from) && related.has(edge.to) ? 'active' : 'dim') : undefined}
            />
          ))}
        </svg>
        {graph.nodes.map((node, index) => (
          <RunMindmapNode
            key={node.key}
            node={node}
            index={index}
            emphasis={related ? (related.has(node.key) ? 'emphasis' : 'dim') : undefined}
            run={snapshot.run}
            percent={graph.percent}
            open={open}
            setActive={setActive}
          />
        ))}
      </div>
      <div className="wb-mm-top-controls" data-mm-controls>
        {follow !== undefined && (
          <button
            className="wb-mm-icon-button wb-mm-follow"
            type="button"
            data-wb-focus="mindmap-follow"
            aria-label={t('wbMindmapFollow')}
            aria-pressed={following}
            title={t(following ? 'wbMindmapFollowOff' : 'wbMindmapFollowOn')}
            onClick={() => controlsRef.current?.toggleFollow()}
          >
            <svg className="wb-icon" viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="6" />
              <circle cx="12" cy="12" r="2" />
              <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
            </svg>
          </button>
        )}
        {back && (
          <button
            className="wb-mm-icon-button wb-back"
            type="button"
            aria-label={t('wbBack')}
            data-wb-focus="back"
            onClick={back}
          >
            <Icon name="back" />
          </button>
        )}
      </div>
      <div className="wb-mm-legend" aria-label={t('status')}>
        {['In Progress', 'Completed', 'Blocked', 'Pending'].map((value) => (
          <span className="wb-mm-state" data-status={stateKind(value)} key={value}>
            <i />
            {status(value)}
          </span>
        ))}
      </div>
      <div className="wb-mm-camera-controls" data-mm-controls>
        <button
          className="wb-mm-icon-button"
          type="button"
          aria-label={t('wbMindmapZoomOut')}
          onClick={() => controlsRef.current?.zoom(1 / 1.2)}
        >
          <svg className="wb-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 12h12" />
          </svg>
        </button>
        <button
          className="wb-mm-icon-button"
          type="button"
          aria-label={t('wbMindmapFit')}
          onClick={() => controlsRef.current?.fit()}
        >
          <Icon name="focus" />
        </button>
        <button
          className="wb-mm-icon-button"
          type="button"
          aria-label={t('wbMindmapZoomIn')}
          onClick={() => controlsRef.current?.zoom(1.2)}
        >
          <svg className="wb-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 12h12M12 6v12" />
          </svg>
        </button>
      </div>
    </div>
  );
}

/** Hover only rerenders cards whose emphasis changes; locale updates still flow through context. */
const RunMindmapNode = memo(function RunMindmapNode({
  node,
  index,
  emphasis,
  run,
  percent,
  open,
  setActive
}: {
  node: MindmapNode;
  index: number;
  emphasis?: 'emphasis' | 'dim';
  run: TaplWorkflowRun;
  percent: number;
  open: (item: TaplItem, run?: TaplWorkflowRun) => void;
  setActive: (key?: string) => void;
}): JSX.Element {
  const { t, status } = useI18n();
  const nodeContent = (node: MindmapNode) => (
    <>
      <span className="wb-mm-meta">
        <span className="wb-mm-id">{node.kind === 'run' ? 'RUN' : node.item?.stable_id}</span>
        {node.status && (
          <span className="wb-mm-state" data-status={stateKind(node.status)}>
            <i />
            {status(node.status)}
          </span>
        )}
      </span>
      <span className="wb-mm-title" title={node.title}>
        {node.title || (node.kind === 'run' ? run.slug || run.id : '')}
      </span>
      {node.kind === 'run' && (
        <span className="wb-mm-run-foot">
          <span className="wb-mm-run-numbers">
            <span className="wb-mm-percent">
              {Math.round(percent)}
              <small>%</small>
            </span>
            <span>
              {node.completed} / {node.total} {t('wbCompleted')}
            </span>
          </span>
          <svg className="wb-mm-ring" viewBox="0 0 48 48" aria-hidden="true">
            <circle className="wb-mm-ring-track" cx="24" cy="24" r="19" />
            <circle
              className="wb-mm-ring-value"
              cx="24"
              cy="24"
              r="19"
              pathLength="100"
              strokeDasharray={`${percent} 100`}
            />
          </svg>
        </span>
      )}
      {node.kind === 'plan' && (
        <span className="wb-mm-plan-foot">
          <span>
            {node.completed} / {node.total} {t('wbCompleted')}
          </span>
          <span className="wb-mm-plan-track">
            <i style={{ width: `${node.total ? (node.completed / node.total) * 100 : 0}%` }} />
          </span>
        </span>
      )}
    </>
  );
  return (
    <div
      className={`wb-mm-node${emphasis ? ` wb-mm-${emphasis}` : ''}`}
      data-kind={node.kind}
      data-mindmap-node={node.key}
      style={
        {
          width: node.width,
          height: node.height,
          transform: `translate(${node.x - node.width / 2}px, ${node.y - node.height / 2}px)`,
          '--mm-order': index
        } as CSSProperties
      }
      onPointerEnter={(event) => {
        if (event.pointerType !== 'touch') setActive(node.key);
      }}
      onPointerLeave={() => setActive(undefined)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setActive(undefined);
      }}
    >
      {node.kind === 'run' ? (
        <div className="wb-mm-node-button" tabIndex={0}>
          {nodeContent(node)}
        </div>
      ) : (
        <button
          className="wb-mm-node-button"
          type="button"
          disabled={!openable(node.item)}
          title={!openable(node.item) ? t('wbRecordUnavailable') : undefined}
          data-wb-focus={`${node.kind}:${node.item?.id ?? node.key}`}
          data-status={node.status}
          onClick={() => {
            if (openable(node.item)) open(node.item!, run);
          }}
        >
          {nodeContent(node)}
        </button>
      )}
    </div>
  );
});

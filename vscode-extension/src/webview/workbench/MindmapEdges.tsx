import { memo } from 'react';

type Edge = { from: string; to: string; path: string; start: { x: number; y: number } };

/** Preserve one path and pulse per edge, in graph order, for the viewport's DOM arrays. */
export const MindmapEdge = memo(function MindmapEdge({
  edge,
  emphasis,
  relation
}: {
  edge: Edge;
  emphasis?: 'active' | 'dim';
  relation?: string;
}): JSX.Element {
  return (
    <g
      data-from={relation ? edge.from : undefined}
      data-to={relation ? edge.to : undefined}
      data-relation={relation}
      className={emphasis ? `wb-mm-edge-${emphasis}` : ''}
    >
      <path className="wb-mm-edge" d={edge.path} />
      <circle className="wb-mm-pulse" r="2" cx={edge.start.x} cy={edge.start.y} />
    </g>
  );
});

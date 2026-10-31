import {
  BaseEdge,
  getBezierPath,
  Position,
  useInternalNode,
  type EdgeProps,
} from "@xyflow/react";

interface Point {
  x: number;
  y: number;
}

/**
 * Centre of a node in flow coordinates. The measurement is only available
 * after React Flow has measured the card; before that we fall back to the
 * handle position so the edge still renders.
 */
function nodeCentre(node: ReturnType<typeof useInternalNode>): Point | null {
  if (!node) return null;
  const width = node.measured?.width ?? 0;
  const height = node.measured?.height ?? 0;
  if (!width || !height) return null;
  const { positionAbsolute } = node.internals;
  return {
    x: positionAbsolute.x + width / 2,
    y: positionAbsolute.y + height / 2,
  };
}

/**
 * GraphEdge — one relation drawn as a map line, not a circuit wire.
 *
 * The node's connection handles stay at the card's top/bottom (they are how the
 * author starts a connection), but the EDGE ignores them and runs
 * centre-to-centre, underneath the cards. Anchoring to the top/bottom borders
 * made every "backwards" relation loop in an S around its source card, which
 * read as visual noise. The curve direction still follows the dominant axis,
 * so the bezier bows with the flow instead of wrapping around it. No
 * arrowheads: direction is out of scope by the Owner's decision.
 */
export function GraphEdge({
  id,
  source,
  target,
  sourceX,
  sourceY,
  targetX,
  targetY,
  style,
}: EdgeProps) {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);
  const from = nodeCentre(sourceNode) ?? { x: sourceX, y: sourceY };
  const to = nodeCentre(targetNode) ?? { x: targetX, y: targetY };

  const horizontal = Math.abs(to.x - from.x) >= Math.abs(to.y - from.y);
  const forward = horizontal ? to.x >= from.x : to.y >= from.y;

  const [path] = getBezierPath({
    sourceX: from.x,
    sourceY: from.y,
    sourcePosition: horizontal
      ? forward
        ? Position.Right
        : Position.Left
      : forward
        ? Position.Bottom
        : Position.Top,
    targetX: to.x,
    targetY: to.y,
    targetPosition: horizontal
      ? forward
        ? Position.Left
        : Position.Right
      : forward
        ? Position.Top
        : Position.Bottom,
    curvature: 0.18,
  });

  return <BaseEdge id={id} path={path} style={style} />;
}

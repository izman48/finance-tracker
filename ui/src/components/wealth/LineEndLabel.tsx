/** The name at a chart line's right end (ux T-11-2 "Lines on"), so lines are
 *  told apart by name, not colour alone. Recharts calls the returned
 *  function for every point; only the last one draws. */
export function lineEndLabel(name: string, colour: string, lastIndex: number) {
  return (props: { x?: number | string; y?: number | string; index?: number }) => {
    if (props.index !== lastIndex || props.x == null || props.y == null) return null
    return (
      <text x={Number(props.x) + 6} y={Number(props.y)} dy={4} fill={colour} fontSize={11}>
        {name}
      </text>
    )
  }
}

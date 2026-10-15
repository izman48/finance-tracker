/** A stored regex rule the matching engine (RE2) can't run (sec-1 on #248):
 *  it would otherwise quietly match nothing. The reason is the API's. */
export default function CantRunNote({ reason }: { reason: string | null | undefined }) {
  if (!reason) return null
  return (
    <span className="block mt-1">
      <span className="chip-warn">This rule can&apos;t run</span>
      <span className="block text-xs text-slate-400 mt-0.5">{reason}</span>
    </span>
  )
}

import { NetWorthChange, NetWorthPosition } from '../services/api'
import { gbp0 as gbp, dateLong, changeTone, signedGbp, signedPct } from '../lib/format'
import InfoTip from './ui/InfoTip'
import { EXPLAIN } from '../copy/statExplainers'

function Cell({ c }: { c: NetWorthChange }) {
  if (!c.available) {
    return (
      <div className="min-w-0" title="We don't hold data going back this far yet.">
        <div className="text-xs text-slate-500 truncate">{c.label}</div>
        <div className="font-semibold tnum text-slate-600">—</div>
        <div className="text-[11px] text-slate-600">no data yet</div>
      </div>
    )
  }
  const change = Number(c.change)
  const pct = signedPct(c.change_pct)
  return (
    <div className="min-w-0" title={c.from_date ? `From ${gbp(Number(c.from_value))} on ${dateLong(c.from_date)}` : undefined}>
      <div className="text-xs text-slate-500 truncate">{c.label}</div>
      <div className={`font-semibold tnum ${changeTone(change)}`}>{signedGbp(change)}</div>
      <div className={`text-[11px] tnum ${pct ? changeTone(change) : 'text-slate-600'}`}>{pct ?? 'from £0'}</div>
    </div>
  )
}

/**
 * How far net worth has moved over each horizon — the "am I getting richer?"
 * answer in one row. Every figure is reconstructed from the same history as
 * the chart, so the two always agree.
 */
export default function PositionStrip({ position }: { position: NetWorthPosition }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-sm text-slate-400 mb-3">
        Your position
        <InfoTip text={EXPLAIN.position} align="left" />
      </div>
      <div className="grid grid-cols-3 sm:grid-cols-5 gap-x-4 gap-y-3">
        {position.changes.map((c) => (
          <Cell key={c.key} c={c} />
        ))}
      </div>
      {position.since && (
        <div className="text-xs text-slate-500 mt-3">
          Tracking since {dateLong(position.since)}
          {' · '}
          {gbp(Number(position.bank))} in banks + {gbp(Number(position.assets))} in assets you've added
        </div>
      )}
    </div>
  )
}

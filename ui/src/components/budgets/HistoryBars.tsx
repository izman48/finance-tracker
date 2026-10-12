import { barHeight, chartMax } from '../../lib/budgetHistory'

export interface HistoryBar {
  key: string
  /** The bar's full sentence (BH11): dates, spent, limit and result. */
  label: string
  /** within: filled; over: outlined, never red (BH8); paused: a dashed slot (BH5);
   *  empty: before the budget existed (BH4); now: hatched, still running (BH9). */
  kind: 'within' | 'over' | 'paused' | 'empty' | 'now'
  value: number
  /** That cycle's limit (a dashed line), or none. */
  limit: number | null
  tick?: string
}

const HATCH = 'repeating-linear-gradient(135deg, rgba(255,255,255,.18) 0 3px, transparent 3px 6px)'

const BAR_CLASS: Record<HistoryBar['kind'], string> = {
  within: 'bg-accent/60',
  over: 'border-[1.5px] border-b-0 border-slate-300/60',
  paused: 'border border-dashed border-white/25',
  empty: '',
  now: 'border border-dashed border-b-0 border-white/30',
}

/** One bar per cycle, oldest left, each against its own dashed limit line. */
export default function HistoryBars({ bars, height, ticks = false }: { bars: HistoryBar[]; height: number; ticks?: boolean }) {
  const max = chartMax(bars.flatMap((b) => [b.value, b.limit ?? 0]))
  const pausedHeight = 60 // a dashed slot of its own, not a value
  return (
    <div>
      <div className="flex items-end gap-1.5 sm:gap-2.5" style={{ height }}>
        {bars.map((b) => {
          const h = b.kind === 'paused' ? pausedHeight : b.kind === 'empty' ? 0 : barHeight(b.value, max)
          return (
            <div key={b.key} className="relative flex-1 max-w-16 h-full flex items-end">
              <div
                role="img"
                aria-label={b.label}
                data-kind={b.kind}
                className={`w-full rounded-t-[5px] motion-safe:transition-[height] ${BAR_CLASS[b.kind]}`}
                style={{ height: `${h}%`, ...(b.kind === 'now' ? { background: HATCH } : {}) }}
              />
              {b.limit !== null && (
                <div
                  aria-hidden="true"
                  data-limit
                  className="absolute -left-0.5 -right-0.5 border-t-[1.5px] border-dashed border-slate-100/55"
                  style={{ bottom: `${barHeight(b.limit, max)}%` }}
                />
              )}
            </div>
          )
        })}
      </div>
      {ticks && (
        <div aria-hidden="true" className="flex gap-1.5 sm:gap-2.5 mt-1.5">
          {bars.map((b) => (
            <span key={b.key} className="flex-1 max-w-16 text-center text-[11px] text-slate-400 whitespace-nowrap">
              {b.tick}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { analyticsAPI } from '../services/api'
import AnimatedNumber from './ui/AnimatedNumber'
import InfoTip from './ui/InfoTip'
import { EXPLAIN } from '../copy/statExplainers'

export default function SpendingSnapshot({ refreshKey }: { refreshKey?: number }) {
  const [data, setData] = useState<{ total_spent: number; charged_to_credit: number; paid_from_cash: number } | null>(null)

  useEffect(() => {
    analyticsAPI
      .getSpending('since_payday')
      .then((res) => {
        const d = res.data
        setData({
          total_spent: Number(d.total_spent),
          charged_to_credit: Number(d.charged_to_credit),
          paid_from_cash: Number(d.paid_from_cash),
        })
      })
      .catch((e) => console.error('Failed to load spending snapshot', e))
  }, [refreshKey])

  if (!data) return null

  const gbp = (n: number) => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(n)
  const creditShare = data.total_spent > 0 ? (data.charged_to_credit / data.total_spent) * 100 : 0

  return (
    <div className="card-pad h-full flex flex-col">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="font-display font-semibold text-slate-100 flex items-center gap-1.5">
          Spent since payday
          <InfoTip text={EXPLAIN.spentSincePayday} side="bottom" align="left" />
        </h2>
        <Link to="/insights" className="btn-link whitespace-nowrap">
          Where it went →
        </Link>
      </div>
      <div className="stat-figure text-4xl text-slate-50 mb-4">
        <AnimatedNumber value={data.total_spent} />
      </div>

      {/* Cash vs credit split bar */}
      <div className="h-2 rounded-full bg-white/[0.06] overflow-hidden flex mb-3" aria-hidden>
        <div className="bg-accent h-full" style={{ width: `${100 - creditShare}%` }} />
        <div className="bg-warn h-full" style={{ width: `${creditShare}%` }} />
      </div>

      <div className="flex gap-6 text-sm">
        <div>
          <div className="flex items-center gap-1.5 text-slate-500">
            <span className="w-2 h-2 rounded-full bg-accent inline-block" /> From cash
            <InfoTip text={EXPLAIN.paidFromCash} align="left" />
          </div>
          <div className="font-semibold text-slate-100 tnum">{gbp(data.paid_from_cash)}</div>
        </div>
        <div>
          <div className="flex items-center gap-1.5 text-slate-500">
            <span className="w-2 h-2 rounded-full bg-warn inline-block" /> On credit
            <InfoTip text={EXPLAIN.chargedToCredit} align="right" />
          </div>
          <div className="font-semibold text-warn tnum">{gbp(data.charged_to_credit)}</div>
        </div>
      </div>
    </div>
  )
}

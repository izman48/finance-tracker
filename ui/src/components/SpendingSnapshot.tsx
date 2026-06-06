import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { analyticsAPI } from '../services/api'

const gbp = (n: number) => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(n)

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

  return (
    <div className="p-6 bg-white rounded-xl shadow-sm border border-gray-200">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-lg font-semibold">Spent since payday</h2>
        <Link to="/insights" className="text-sm text-blue-600 hover:text-blue-800">
          Where it went →
        </Link>
      </div>
      <div className="text-3xl font-bold mb-3">{gbp(data.total_spent)}</div>
      <div className="flex gap-6 text-sm">
        <div>
          <div className="text-gray-500">From cash</div>
          <div className="font-semibold">{gbp(data.paid_from_cash)}</div>
        </div>
        <div>
          <div className="text-gray-500">On credit</div>
          <div className="font-semibold text-amber-600">{gbp(data.charged_to_credit)}</div>
        </div>
      </div>
    </div>
  )
}

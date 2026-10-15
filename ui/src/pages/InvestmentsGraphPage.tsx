import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import axios from 'axios'
import { holdingsAPI } from '../services/api'
import InvestmentGraphView, { type InvestmentGraphViewProps } from '../components/wealth/InvestmentGraphView'
import { graphDefaultGrowth, wealthFormLink, type InvestmentGraph } from '../lib/investments'

/** Wealth > Investments graph (`/networth/investments`, ux T-11-2 flow 3).
 *  The chosen holding is in the URL (`?holding=<id>`), so Back and reload
 *  keep it; an id that isn't the user's gets the API's 404 and the "no
 *  investments" state, with nothing about it shown. */
export default function InvestmentsGraphPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const holdingId = params.get('holding')
  const [months, setMonths] = useState(120)
  const [graph, setGraph] = useState<InvestmentGraph | null>(null)
  const [status, setStatus] = useState<InvestmentGraphViewProps['status']>('loading')
  // The selector lists every investment, whichever one is shown (eng-a on #217).
  const [options, setOptions] = useState<{ id: string; name: string }[]>([])

  const loadOptions = useCallback(async () => {
    try {
      const res = await holdingsAPI.projection({ months: 1 })
      setOptions((res.data.holdings ?? []).map((h) => ({ id: h.id, name: h.name })))
    } catch {
      setOptions([])
    }
  }, [])

  useEffect(() => { void loadOptions() }, [loadOptions])

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const growth = graphDefaultGrowth(localStorage.getItem('wealth.growth'))
      const res = await holdingsAPI.projection({ months, holding_id: holdingId, annual_growth_pct: growth })
      setGraph(res.data)
      setStatus('ready')
    } catch (err) {
      setGraph(null)
      setStatus(axios.isAxiosError(err) && (err.response?.status === 404 || err.response?.status === 422) ? 'not_found' : 'error')
    }
  }, [months, holdingId])

  useEffect(() => { void load() }, [load])

  const chooseHolding = (id: string | null) => {
    const next = new URLSearchParams(params)
    if (id) next.set('holding', id)
    else next.delete('holding')
    setParams(next)
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 sm:py-10">
      <Link to="/networth" className="inline-flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200 mb-4">
        <ArrowLeft className="w-4 h-4" aria-hidden="true" /> Wealth
      </Link>
      <InvestmentGraphView
        status={status}
        graph={graph}
        months={months}
        holdingId={holdingId}
        options={options}
        onMonths={setMonths}
        onHolding={chooseHolding}
        onRetry={() => { void load(); void loadOptions() }}
        onAdd={() => navigate(wealthFormLink({ add: true }))}
        onEditGrowth={(id) => navigate(wealthFormLink({ edit: id }))}
      />
    </div>
  )
}

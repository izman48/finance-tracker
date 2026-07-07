import { Landmark, Pencil, TrendingDown, ChevronRight } from 'lucide-react'

/** The universal "add" entry point on Wealth: connect a bank (automatic,
 *  first and highlighted), track an asset manually, or record a liability.
 *  Keeping the connect path inside every add flow is what makes "you can
 *  connect more banks" permanently discoverable. */
export default function AddToBalanceSheetChooser({
  providers,
  onConnect,
  onManual,
  onLiability,
  onClose,
}: {
  providers: string[]
  onConnect: () => void
  onManual: () => void
  onLiability: () => void
  onClose: () => void
}) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-1">Add to your balance sheet</h3>
        <p className="text-sm text-slate-400 mb-4">Everything you own and owe, in one place.</p>

        <button
          onClick={onConnect}
          className="w-full text-left flex items-start gap-3 p-4 rounded-xl border border-accent/40 bg-accent/10 hover:bg-accent/15 transition-colors mb-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          autoFocus
        >
          <Landmark className="w-5 h-5 text-accent shrink-0 mt-0.5" />
          <span className="flex-1 min-w-0">
            <span className="block font-medium text-accent">
              {providers.length > 0 ? 'Connect another bank' : 'Connect a bank'}
            </span>
            <span className="block text-sm text-slate-400 mt-0.5">
              Current accounts, savings and credit cards update automatically. You can
              connect as many banks as you like.
            </span>
          </span>
          <ChevronRight className="w-4 h-4 text-accent shrink-0 mt-1" />
        </button>

        <button
          onClick={onManual}
          className="w-full text-left flex items-start gap-3 p-4 rounded-xl border border-white/10 hover:bg-white/[0.04] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        >
          <Pencil className="w-5 h-5 text-slate-400 shrink-0 mt-0.5" />
          <span className="flex-1 min-w-0">
            <span className="block font-medium text-slate-100">Track an asset manually</span>
            <span className="block text-sm text-slate-400 mt-0.5">
              ISAs, pensions, property, crypto — anything your bank doesn't know about.
            </span>
          </span>
          <ChevronRight className="w-4 h-4 text-slate-500 shrink-0 mt-1" />
        </button>

        <button
          onClick={onLiability}
          className="w-full text-left flex items-start gap-3 p-4 rounded-xl border border-white/10 hover:bg-white/[0.04] transition-colors mt-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        >
          <TrendingDown className="w-5 h-5 text-slate-400 shrink-0 mt-0.5" />
          <span className="flex-1 min-w-0">
            <span className="block font-medium text-slate-100">Add a liability</span>
            <span className="block text-sm text-slate-400 mt-0.5">
              A mortgage, loan or other debt — subtracted from your net worth.
            </span>
          </span>
          <ChevronRight className="w-4 h-4 text-slate-500 shrink-0 mt-1" />
        </button>

        {providers.length > 0 && (
          <p className="text-xs text-slate-500 mt-4">
            {providers.length} bank{providers.length !== 1 ? 's' : ''} connected · {providers.join(', ')}
          </p>
        )}
      </div>
    </div>
  )
}

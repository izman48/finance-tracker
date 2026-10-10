export const RULES_DESCRIPTION =
  "Create new categorisation rule packs. A new pack can recategorise past transactions, but never ones you set by hand. It can't edit or delete your existing rules, and you can remove a pack in Rules."

export const PLANNING_DESCRIPTION =
  "Add planned events, remove ones it added, and edit or dismiss commitments. It's asked to show you a preview before each change. Every change is listed under Changes made by Claude, where you can undo it. Income it adds never raises your safe to spend."

type Props = {
  allowRules: boolean
  allowPlanning: boolean
  onRulesChange: (allowed: boolean) => void
  onPlanningChange: (allowed: boolean) => void
}

/** The permissions an MCP client asks for on the consent screen. Read is always granted. */
export default function ConsentScopes({ allowRules, allowPlanning, onRulesChange, onPlanningChange }: Props) {
  return (
    <ul className="space-y-3">
      <li className="flex gap-3">
        <input type="checkbox" checked disabled className="mt-1 shrink-0 accent-accent" aria-label="Read your finances (required)" />
        <div className="min-w-0">
          <p className="text-sm text-slate-100">Read your finances</p>
          <p className="text-xs text-slate-400">
            Balances, transactions, spending, forecasts, commitments and rules. It can't move money.
          </p>
        </div>
      </li>
      <li className="flex gap-3">
        <input
          id="allow-rules"
          type="checkbox"
          checked={allowRules}
          onChange={(e) => onRulesChange(e.target.checked)}
          className="mt-1 shrink-0 accent-accent"
        />
        <label htmlFor="allow-rules" className="min-w-0 cursor-pointer">
          <span className="block text-sm text-slate-100">Add rule packs</span>
          <span className="block text-xs text-slate-400">{RULES_DESCRIPTION}</span>
        </label>
      </li>
      <li className="flex gap-3">
        {/* Padding grows the tap target past 44px; the negative margin keeps the layout. */}
        <label htmlFor="allow-planning" className="-m-4 p-4 shrink-0 self-start cursor-pointer">
          <input
            id="allow-planning"
            type="checkbox"
            checked={allowPlanning}
            onChange={(e) => onPlanningChange(e.target.checked)}
            aria-describedby="allow-planning-desc"
            className="mt-1 block accent-accent"
          />
        </label>
        <div className="min-w-0">
          <label htmlFor="allow-planning" className="block text-sm text-slate-100 cursor-pointer">
            Change your planned events and commitments
          </label>
          <p id="allow-planning-desc" className="text-xs text-slate-400">{PLANNING_DESCRIPTION}</p>
        </div>
      </li>
    </ul>
  )
}

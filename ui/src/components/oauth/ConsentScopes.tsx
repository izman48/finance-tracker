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
      <li>
        {/* The whole row is the label, so the tap target is the row itself and
            never reaches the rules row above. The input is named by its title only. */}
        <label htmlFor="allow-planning" className="flex gap-3 cursor-pointer">
          <input
            id="allow-planning"
            type="checkbox"
            checked={allowPlanning}
            onChange={(e) => onPlanningChange(e.target.checked)}
            aria-labelledby="allow-planning-title"
            aria-describedby="allow-planning-desc"
            className="mt-1 shrink-0 accent-accent"
          />
          <span className="min-w-0">
            <span id="allow-planning-title" className="block text-sm text-slate-100">
              Change your planned events and commitments
            </span>
            <span id="allow-planning-desc" className="block text-xs text-slate-400">{PLANNING_DESCRIPTION}</span>
          </span>
        </label>
      </li>
    </ul>
  )
}

export const RULES_DESCRIPTION =
  "Create new categorisation rule packs. A new pack can recategorise past transactions, but never ones you set by hand. It can't edit or delete your existing rules, and you can remove a pack in Rules."

export const PLANNING_DESCRIPTION =
  "Add planned events, remove ones it added, and edit or dismiss commitments. It's asked to show you a preview before each change. Every change is listed under Changes made by Claude, where you can undo it. Nothing it changes raises your safe to spend or savable until you keep it in nilu."

export const SYNC_DESCRIPTION =
  "Ask nilu. to fetch new data from your connected banks. It can't connect, reconnect or disconnect a bank. Limited to once every 10 minutes, shared with the app."

export const BUDGETS_DESCRIPTION =
  "Set, change, pause, resume or remove your budgets. It's asked to show you a preview before each change. Changes take effect at once, and every one is listed under Changes made by Claude, where you can undo it. Budgets never change your safe to spend."

export const RULES_EDIT_DESCRIPTION =
  "Edit or switch off your existing categorisation rules. It's asked to show you a preview before each change. An edited rule can recategorise past transactions, but never ones you set by hand. Every change is listed under Changes made by Claude, where you can undo it."

type Props = {
  allowRules: boolean
  allowPlanning: boolean
  allowSync: boolean
  allowBudgets: boolean
  allowRulesEdit: boolean
  onRulesChange: (allowed: boolean) => void
  onPlanningChange: (allowed: boolean) => void
  onSyncChange: (allowed: boolean) => void
  onBudgetsChange: (allowed: boolean) => void
  onRulesEditChange: (allowed: boolean) => void
}

/** The permissions an MCP client asks for on the consent screen. Read is always granted. */
export default function ConsentScopes({
  allowRules,
  allowPlanning,
  allowSync,
  allowBudgets,
  allowRulesEdit,
  onRulesChange,
  onPlanningChange,
  onSyncChange,
  onBudgetsChange,
  onRulesEditChange,
}: Props) {
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
      <li>
        <label htmlFor="allow-sync" className="flex gap-3 cursor-pointer">
          <input
            id="allow-sync"
            type="checkbox"
            checked={allowSync}
            onChange={(e) => onSyncChange(e.target.checked)}
            aria-labelledby="allow-sync-title"
            aria-describedby="allow-sync-desc"
            className="mt-1 shrink-0 accent-accent"
          />
          <span className="min-w-0">
            <span id="allow-sync-title" className="block text-sm text-slate-100">
              Refresh your bank data
            </span>
            <span id="allow-sync-desc" className="block text-xs text-slate-400">{SYNC_DESCRIPTION}</span>
          </span>
        </label>
      </li>
      <li>
        <label htmlFor="allow-budgets" className="flex gap-3 cursor-pointer">
          <input
            id="allow-budgets"
            type="checkbox"
            checked={allowBudgets}
            onChange={(e) => onBudgetsChange(e.target.checked)}
            aria-labelledby="allow-budgets-title"
            aria-describedby="allow-budgets-desc"
            className="mt-1 shrink-0 accent-accent"
          />
          <span className="min-w-0">
            <span id="allow-budgets-title" className="block text-sm text-slate-100">
              Set and manage your budgets
            </span>
            <span id="allow-budgets-desc" className="block text-xs text-slate-400">{BUDGETS_DESCRIPTION}</span>
          </span>
        </label>
      </li>
      <li>
        <label htmlFor="allow-rules-edit" className="flex gap-3 cursor-pointer">
          <input
            id="allow-rules-edit"
            type="checkbox"
            checked={allowRulesEdit}
            onChange={(e) => onRulesEditChange(e.target.checked)}
            aria-labelledby="allow-rules-edit-title"
            aria-describedby="allow-rules-edit-desc"
            className="mt-1 shrink-0 accent-accent"
          />
          <span className="min-w-0">
            <span id="allow-rules-edit-title" className="block text-sm text-slate-100">
              Edit your existing rules
            </span>
            <span id="allow-rules-edit-desc" className="block text-xs text-slate-400">{RULES_EDIT_DESCRIPTION}</span>
          </span>
        </label>
      </li>
    </ul>
  )
}

import { useState } from 'react'
import axios from 'axios'
import { analyticsAPI } from '../services/api'
import type { PlannedItem } from '../types'

/** Tick or untick "Card payment" on an existing planned expense (T-12-7a),
 *  so an item added before the tick existed can count once with the
 *  projected card bills. A native checkbox: Space toggles it. */
export default function CardPaymentToggle({ item, onChanged }: { item: PlannedItem; onChanged: () => void }) {
  const [on, setOn] = useState(Boolean(item.is_card_payment))
  const [saving, setSaving] = useState(false)
  const [failed, setFailed] = useState(false)

  const toggle = async (next: boolean) => {
    setSaving(true)
    setFailed(false)
    try {
      await analyticsAPI.setPlannedCardPayment(item.id, next)
      setOn(next)
      onChanged()
    } catch (err) {
      // Demo mode blocks the write and says so in a toast; the box stays as it was.
      if (!axios.isCancel(err)) setFailed(true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <label className="inline-flex items-center gap-1.5 min-h-[44px] whitespace-nowrap text-sm text-slate-400">
      <input
        type="checkbox"
        checked={on}
        disabled={saving}
        onChange={(e) => toggle(e.target.checked)}
        aria-label={`Card payment: ${item.name}`}
        className="checkbox"
      />
      Card payment
      {failed && <span role="alert" className="text-neg">Couldn&apos;t save. Try again.</span>}
    </label>
  )
}

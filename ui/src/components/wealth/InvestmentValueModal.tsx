import { useEffect, useRef, useState, type FormEvent } from 'react'
import axios from 'axios'
import Sheet from '../ui/Sheet'
import { assetsAPI, type Asset } from '../../services/api'
import { lastValueLine, parseValueToday } from '../../lib/investments'

/** "Update value" for an investment (ux T-11-2): one field that overwrites
 *  today's value with one request, so the forecast re-bases from today. No
 *  "added or withdrawn" field (A8): it would confuse "paid in". */
export default function InvestmentValueModal({ asset, now = Date.now(), onClose, onSaved }: {
  asset: Asset
  now?: number
  onClose: () => void
  onSaved: () => void
}) {
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  // After the sheet has focused its panel: the field, selected (ux).
  useEffect(() => {
    const id = window.setTimeout(() => { input.current?.focus(); input.current?.select() }, 0)
    return () => window.clearTimeout(id)
  }, [])

  const save = async (e: FormEvent) => {
    e.preventDefault()
    const parsed = parseValueToday(value)
    if (parsed === null) {
      setError('Enter the value today, 0 or more.')
      input.current?.focus()
      return
    }
    setSaving(true)
    setError(null)
    try {
      await assetsAPI.addValuation(asset.id, { value: parsed })
      onSaved()
    } catch (err) {
      setSaving(false)
      // A demo-mode block already shows its own toast.
      if (!axios.isCancel(err)) setError('We could not save this. Nothing changed. Try again.')
    }
  }

  return (
    <Sheet title="Update value" onClose={onClose}>
      <form onSubmit={save} noValidate>
        <p className="text-sm text-slate-400 mb-4">{lastValueLine(asset, now)}</p>
        <label htmlFor="investment-value" className="label">Value today (£)</label>
        <input
          id="investment-value"
          ref={input}
          className="input"
          inputMode="decimal"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-invalid={error === 'Enter the value today, 0 or more.' || undefined}
          aria-describedby={error ? 'investment-value-error' : undefined}
        />
        {error && <p id="investment-value-error" role="alert" className="text-sm text-neg mt-1.5">{error}</p>}
        <div className="flex justify-end gap-2 mt-5">
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Update value'}</button>
        </div>
      </form>
    </Sheet>
  )
}

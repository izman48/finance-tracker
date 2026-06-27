import { useCallback, useEffect, useRef, useState } from 'react'
import { rulesAPI, RulePack } from '../services/api'

/**
 * Create-rule modal, usable from the Rules page or in context from the
 * Transactions page (pass initialPattern/initialCategory to prefill).
 */
export default function AddRuleModal({
  initialPackId = null,
  initialPattern = '',
  initialCategory = '',
  categories = [],
  onClose,
  onAdded,
}: {
  initialPackId?: string | null
  initialPattern?: string
  initialCategory?: string
  categories?: string[]
  onClose: () => void
  onAdded: (result?: { applied: boolean; changed: number }) => void
}) {
  const [packs, setPacks] = useState<RulePack[]>([])
  const [pattern, setPattern] = useState(initialPattern)
  const [matchType, setMatchType] = useState('contains')
  const [matchField, setMatchField] = useState('any')
  const [category, setCategory] = useState(initialCategory)
  const [packId, setPackId] = useState<string | null>(initialPackId)
  const [preview, setPreview] = useState<{ match_count: number; total_transactions: number; samples: any[] } | null>(null)
  const [applyToExisting, setApplyToExisting] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const previewTimer = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    rulesAPI.list().then((res) => setPacks(res.data.packs)).catch(() => {})
  }, [])

  const runPreview = useCallback((p: string, mt: string, mf: string) => {
    clearTimeout(previewTimer.current)
    if (!p.trim()) {
      setPreview(null)
      return
    }
    previewTimer.current = setTimeout(async () => {
      try {
        const res = await rulesAPI.preview({ pattern: p, match_type: mt, match_field: mf })
        setPreview(res.data)
        setError('')
      } catch (e: any) {
        setPreview(null)
        setError(e.response?.data?.detail || '')
      }
    }, 350)
  }, [])

  // Show the prefilled pattern's match count straight away.
  useEffect(() => {
    if (initialPattern) runPreview(initialPattern, 'contains', 'any')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async () => {
    if (!pattern.trim() || !category.trim()) return
    setSaving(true)
    setError('')
    try {
      await rulesAPI.create({ pattern, match_type: matchType, match_field: matchField, category, pack_id: packId })
      // Backfill: by default apply the new rule across existing transactions too,
      // so "make a rule" fixes history, not just future syncs.
      let changed = 0
      if (applyToExisting) {
        const res = await rulesAPI.applyNow()
        changed = res.data?.changed ?? 0
      }
      onAdded({ applied: applyToExisting, changed })
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to save rule')
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-4">New rule</h3>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <select
              value={matchField}
              onChange={(e) => { setMatchField(e.target.value); runPreview(pattern, matchType, e.target.value) }}
              className="input"
            >
              <option value="any">Merchant or description</option>
              <option value="merchant">Merchant only</option>
              <option value="description">Description only</option>
            </select>
            <select
              value={matchType}
              onChange={(e) => { setMatchType(e.target.value); runPreview(pattern, e.target.value, matchField) }}
              className="input"
            >
              <option value="contains">contains</option>
              <option value="exact">is exactly</option>
              <option value="regex">matches regex</option>
            </select>
          </div>

          <input
            value={pattern}
            onChange={(e) => { setPattern(e.target.value); runPreview(e.target.value, matchType, matchField) }}
            placeholder={matchType === 'regex' ? 'e.g. ^AMZN.*MKTP' : 'e.g. deliveroo'}
            className="input font-mono"
            autoFocus={!initialPattern}
          />

          {preview && (
            <div className="bg-white/[0.04] border border-white/[0.06] rounded-xl p-3 text-sm">
              <div className="font-medium text-slate-200">
                Matches {preview.match_count} of your {preview.total_transactions} transactions
              </div>
              {preview.samples.length > 0 && (
                <ul className="mt-1 text-slate-500 text-xs space-y-0.5">
                  {preview.samples.map((s, i) => (
                    <li key={i} className="truncate">• {s.merchant_name || s.description}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {error && <div className="banner-err !p-2">{error}</div>}

          <div>
            <input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="Category (e.g. Food & Drink)"
              list="rule-category-options"
              className="input"
              autoFocus={!!initialPattern}
            />
            <datalist id="rule-category-options">
              {categories.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
            {categories.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {categories.slice(0, 8).map((c) => (
                  <button
                    key={c}
                    onClick={() => setCategory(c)}
                    className={`px-2 py-0.5 text-xs rounded-md transition-colors ${
                      category === c ? 'bg-accent text-ink-950 font-medium' : 'bg-white/[0.07] text-slate-300 hover:bg-white/[0.12]'
                    }`}
                  >
                    {c}
                  </button>
                ))}
              </div>
            )}
          </div>

          <select
            value={packId ?? ''}
            onChange={(e) => setPackId(e.target.value || null)}
            className="input"
          >
            <option value="">No pack (personal rule)</option>
            {packs.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        <label className="flex items-center gap-2 mt-4 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={applyToExisting}
            onChange={(e) => setApplyToExisting(e.target.checked)}
            className="checkbox"
          />
          <span className="text-sm text-slate-300">Apply to existing transactions</span>
          {preview && applyToExisting && (
            <span className="text-xs text-slate-500">(recategorises {preview.match_count} now)</span>
          )}
        </label>

        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={save} disabled={saving || !pattern.trim() || !category.trim()} className="btn-primary">
            {saving ? 'Saving…' : 'Add rule'}
          </button>
        </div>
      </div>
    </div>
  )
}

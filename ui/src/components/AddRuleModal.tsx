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
  onAdded: () => void
}) {
  const [packs, setPacks] = useState<RulePack[]>([])
  const [pattern, setPattern] = useState(initialPattern)
  const [matchType, setMatchType] = useState('contains')
  const [matchField, setMatchField] = useState('any')
  const [category, setCategory] = useState(initialCategory)
  const [packId, setPackId] = useState<string | null>(initialPackId)
  const [preview, setPreview] = useState<{ match_count: number; total_transactions: number; samples: any[] } | null>(null)
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
      onAdded()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to save rule')
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-4">New rule</h3>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <select
              value={matchField}
              onChange={(e) => { setMatchField(e.target.value); runPreview(pattern, matchType, e.target.value) }}
              className="px-3 py-2 border border-gray-300 rounded-lg"
            >
              <option value="any">Merchant or description</option>
              <option value="merchant">Merchant only</option>
              <option value="description">Description only</option>
            </select>
            <select
              value={matchType}
              onChange={(e) => { setMatchType(e.target.value); runPreview(pattern, e.target.value, matchField) }}
              className="px-3 py-2 border border-gray-300 rounded-lg"
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
            className="w-full px-3 py-2 border border-gray-300 rounded-lg font-mono"
            autoFocus={!initialPattern}
          />

          {preview && (
            <div className="bg-gray-50 rounded-lg p-3 text-sm">
              <div className="font-medium">
                Matches {preview.match_count} of your {preview.total_transactions} transactions
              </div>
              {preview.samples.length > 0 && (
                <ul className="mt-1 text-gray-500 text-xs space-y-0.5">
                  {preview.samples.map((s, i) => (
                    <li key={i} className="truncate">• {s.merchant_name || s.description}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {error && <div className="p-2 bg-red-100 text-red-700 rounded text-sm">{error}</div>}

          <div>
            <input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="Category (e.g. Food & Drink)"
              list="rule-category-options"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg"
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
                    className={`px-2 py-0.5 text-xs rounded ${
                      category === c ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
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
            className="w-full px-3 py-2 border border-gray-300 rounded-lg"
          >
            <option value="">No pack (personal rule)</option>
            {packs.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg">Cancel</button>
          <button
            onClick={save}
            disabled={saving || !pattern.trim() || !category.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Add rule'}
          </button>
        </div>
      </div>
    </div>
  )
}

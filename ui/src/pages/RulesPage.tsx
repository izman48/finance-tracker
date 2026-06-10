import { useEffect, useState } from 'react'
import { rulesAPI, Rule, RulePack } from '../services/api'
import AddRuleModal from '../components/AddRuleModal'

const MATCH_TYPE_LABEL: Record<string, string> = {
  exact: 'is exactly',
  contains: 'contains',
  regex: 'matches regex',
}

const FIELD_LABEL: Record<string, string> = {
  any: 'merchant or description',
  merchant: 'merchant',
  description: 'description',
}

export default function RulesPage() {
  const [packs, setPacks] = useState<RulePack[]>([])
  const [personal, setPersonal] = useState<Rule[]>([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [showAddRule, setShowAddRule] = useState<{ packId: string | null } | null>(null)
  const [showImport, setShowImport] = useState(false)
  const [showNewPack, setShowNewPack] = useState(false)

  const load = async () => {
    try {
      const res = await rulesAPI.list()
      setPacks(res.data.packs)
      setPersonal(res.data.personal)
    } catch (e) {
      console.error('Failed to load rules', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const applyNow = async () => {
    setMessage('')
    const res = await rulesAPI.applyNow()
    setMessage(res.data.message)
  }

  const toggleRule = async (rule: Rule) => {
    await rulesAPI.update(rule.id, { enabled: !rule.enabled })
    await load()
  }

  const deleteRule = async (rule: Rule) => {
    await rulesAPI.remove(rule.id)
    await load()
  }

  const togglePack = async (pack: RulePack) => {
    await rulesAPI.updatePack(pack.id, { enabled: !pack.enabled })
    await load()
  }

  const deletePack = async (pack: RulePack) => {
    if (!confirm(`Delete pack "${pack.name}" and its ${pack.rules.length} rules?`)) return
    await rulesAPI.removePack(pack.id)
    await load()
  }

  const sharePack = async (pack: RulePack) => {
    const res = await rulesAPI.sharePack(pack.id)
    await navigator.clipboard.writeText(res.data.share_url).catch(() => {})
    setMessage(`Share link copied: ${res.data.share_url}`)
    await load()
  }

  const unsharePack = async (pack: RulePack) => {
    await rulesAPI.unsharePack(pack.id)
    setMessage('Sharing disabled — the old link no longer works.')
    await load()
  }

  if (loading) {
    return <div className="max-w-5xl mx-auto px-4 py-8 text-center text-gray-600">Loading rules…</div>
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-2">
        <h1 className="text-2xl sm:text-3xl font-bold">Rules</h1>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setShowAddRule({ packId: null })}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            New rule
          </button>
          <button
            onClick={() => setShowNewPack(true)}
            className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
          >
            New pack
          </button>
          <button
            onClick={() => setShowImport(true)}
            className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
          >
            Import
          </button>
        </div>
      </div>
      <p className="text-gray-600 mb-6">
        Rules categorize transactions automatically — now and on every sync. Share a pack with
        friends so they don't have to start from scratch.
      </p>

      {message && (
        <div className="mb-6 p-4 rounded-lg bg-green-100 text-green-800 break-all">{message}</div>
      )}

      <div className="mb-6">
        <button onClick={applyNow} className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700">
          Apply all rules now
        </button>
        <span className="ml-3 text-sm text-gray-500">
          Re-runs every enabled rule over your uncategorized history. Hand-set categories are never touched.
        </span>
      </div>

      {/* Packs */}
      {packs.map((pack) => (
        <div key={pack.id} className={`mb-6 bg-white rounded-lg shadow-sm ${pack.enabled ? '' : 'opacity-60'}`}>
          <div className="px-4 py-3 border-b flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <div>
              <span className="font-semibold">{pack.name}</span>
              {pack.imported_from && (
                <span className="ml-2 text-xs px-2 py-0.5 bg-purple-100 text-purple-700 rounded">imported</span>
              )}
              {pack.share_code && (
                <span className="ml-2 text-xs px-2 py-0.5 bg-blue-100 text-blue-700 rounded">shared</span>
              )}
              {pack.description && <div className="text-sm text-gray-500">{pack.description}</div>}
            </div>
            <div className="flex flex-wrap gap-2 text-sm">
              <button onClick={() => setShowAddRule({ packId: pack.id })} className="text-blue-600 hover:text-blue-800">
                + Add rule
              </button>
              {pack.share_code ? (
                <>
                  <button onClick={() => sharePack(pack)} className="text-gray-500 hover:text-blue-600">Copy link</button>
                  <button onClick={() => unsharePack(pack)} className="text-gray-500 hover:text-red-600">Unshare</button>
                </>
              ) : (
                <button onClick={() => sharePack(pack)} className="text-gray-500 hover:text-blue-600">Share</button>
              )}
              <button onClick={() => togglePack(pack)} className="text-gray-500 hover:text-blue-600">
                {pack.enabled ? 'Disable' : 'Enable'}
              </button>
              <button onClick={() => deletePack(pack)} className="text-gray-400 hover:text-red-600">Delete</button>
            </div>
          </div>
          <RuleList rules={pack.rules} onToggle={toggleRule} onDelete={deleteRule} />
        </div>
      ))}

      {/* Personal (learned + loose manual) rules */}
      <div className="mb-6 bg-white rounded-lg shadow-sm">
        <div className="px-4 py-3 border-b">
          <span className="font-semibold">Personal rules</span>
          <div className="text-sm text-gray-500">
            Created when you categorize transactions, plus any rules you add outside a pack.
          </div>
        </div>
        <RuleList rules={personal} onToggle={toggleRule} onDelete={deleteRule} />
      </div>

      {showAddRule && (
        <AddRuleModal
          initialPackId={showAddRule.packId}
          categories={Array.from(
            new Set([...packs.flatMap((p) => p.rules), ...personal].map((r) => r.category))
          ).sort()}
          onClose={() => setShowAddRule(null)}
          onAdded={async () => {
            setShowAddRule(null)
            await load()
          }}
        />
      )}
      {showNewPack && (
        <NewPackModal
          onClose={() => setShowNewPack(false)}
          onAdded={async () => {
            setShowNewPack(false)
            await load()
          }}
        />
      )}
      {showImport && (
        <ImportModal
          onClose={() => setShowImport(false)}
          onImported={async () => {
            setShowImport(false)
            setMessage('Pack imported — its rules are yours now. Run "Apply all rules now" to use it on your history.')
            await load()
          }}
        />
      )}
    </div>
  )
}

function RuleList({
  rules,
  onToggle,
  onDelete,
}: {
  rules: Rule[]
  onToggle: (r: Rule) => void
  onDelete: (r: Rule) => void
}) {
  if (rules.length === 0) {
    return <div className="p-4 text-sm text-gray-400">No rules yet.</div>
  }
  return (
    <div className="divide-y">
      {rules.map((r) => (
        <div key={r.id} className={`p-3 px-4 flex items-center justify-between gap-3 ${r.enabled ? '' : 'opacity-50'}`}>
          <div className="min-w-0 text-sm">
            <span className="text-gray-500">{FIELD_LABEL[r.match_field]} {MATCH_TYPE_LABEL[r.match_type]} </span>
            <span className="font-mono font-medium break-all">{r.pattern}</span>
            <span className="text-gray-500"> → </span>
            <span className="inline-block px-2 py-0.5 text-xs bg-gray-100 text-gray-700 rounded">{r.category}</span>
            {r.source === 'learned' && (
              <span className="ml-1 text-xs text-gray-400">(learned)</span>
            )}
          </div>
          <div className="flex gap-2 text-sm whitespace-nowrap">
            <button onClick={() => onToggle(r)} className="text-gray-500 hover:text-blue-600">
              {r.enabled ? 'Disable' : 'Enable'}
            </button>
            <button onClick={() => onDelete(r)} className="text-gray-400 hover:text-red-600">
              Delete
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

function NewPackModal({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (!name.trim()) return
    setSaving(true)
    await rulesAPI.createPack({ name, description: description || undefined })
    onAdded()
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-1">New pack</h3>
        <p className="text-sm text-gray-500 mb-4">A named set of rules you can share as one link.</p>
        <div className="space-y-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name (e.g. UK Essentials)"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg"
            autoFocus
          />
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description (optional)"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg"
          />
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg">Cancel</button>
          <button
            onClick={save}
            disabled={saving || !name.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? 'Creating…' : 'Create pack'}
          </button>
        </div>
      </div>
    </div>
  )
}

export function ImportModal({
  initialCode,
  onClose,
  onImported,
}: {
  initialCode?: string
  onClose: () => void
  onImported: () => void
}) {
  const [code, setCode] = useState(initialCode ?? '')
  const [preview, setPreview] = useState<any | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const extractCode = (raw: string) => {
    const m = raw.trim().match(/\/r\/([A-Za-z0-9_-]+)/)
    return m ? m[1] : raw.trim()
  }

  const lookup = async () => {
    setError('')
    setPreview(null)
    setBusy(true)
    try {
      const res = await rulesAPI.previewShared(extractCode(code))
      setPreview(res.data)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Share link not found')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (initialCode) lookup()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const doImport = async () => {
    setBusy(true)
    setError('')
    try {
      await rulesAPI.importPack(extractCode(code))
      onImported()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Import failed')
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-1">Import a rule pack</h3>
        <p className="text-sm text-gray-500 mb-4">
          Paste a share link or code. You get your own copy — the author can't change it afterwards.
        </p>

        <div className="flex gap-2">
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="https://…/r/AB12CD or AB12CD"
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg"
            autoFocus
          />
          <button
            onClick={lookup}
            disabled={busy || !code.trim()}
            className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50"
          >
            Look up
          </button>
        </div>

        {error && <div className="mt-3 p-2 bg-red-100 text-red-700 rounded text-sm">{error}</div>}

        {preview && (
          <div className="mt-4 bg-gray-50 rounded-lg p-3">
            <div className="font-medium">{preview.name}</div>
            {preview.description && <div className="text-sm text-gray-500">{preview.description}</div>}
            <div className="text-sm text-gray-600 mt-1">{preview.rule_count} rules</div>
            <ul className="mt-2 text-xs text-gray-500 space-y-0.5 max-h-32 overflow-y-auto">
              {preview.rules.map((r: any, i: number) => (
                <li key={i} className="truncate">
                  <span className="font-mono">{r.pattern}</span> → {r.category}
                </li>
              ))}
            </ul>
            {preview.already_owned && (
              <div className="mt-2 text-xs text-amber-600">This is your own pack.</div>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg">Cancel</button>
          <button
            onClick={doImport}
            disabled={busy || !preview || preview.already_owned}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? 'Importing…' : 'Import pack'}
          </button>
        </div>
      </div>
    </div>
  )
}

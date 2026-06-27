import { useEffect, useState } from 'react'
import { rulesAPI, Rule, RulePack } from '../services/api'
import AddRuleModal from '../components/AddRuleModal'
import useReveal from '../components/ui/useReveal'

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

  const revealRef = useReveal(!loading)

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
    return <div className="max-w-5xl mx-auto px-4 py-8 text-center text-slate-500">Loading rules…</div>
  }

  return (
    <div ref={revealRef} className="max-w-5xl mx-auto px-4 py-6 sm:py-10">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-2">
        <h1 className="font-display font-bold text-2xl sm:text-3xl text-slate-50">Rules</h1>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setShowAddRule({ packId: null })} className="btn-primary">
            New rule
          </button>
          <button onClick={() => setShowNewPack(true)} className="btn-ghost">
            New pack
          </button>
          <button onClick={() => setShowImport(true)} className="btn-ghost">
            Import
          </button>
        </div>
      </div>
      <p className="text-slate-400 mb-6">
        Rules categorize transactions automatically — now and on every sync. Share a pack with
        friends so they don't have to start from scratch.
      </p>

      {message && <div className="banner-ok mb-6 break-all">{message}</div>}

      <div className="mb-6 flex flex-wrap items-center gap-3" data-reveal>
        <button onClick={applyNow} className="btn-ghost !text-accent">
          Apply all rules now
        </button>
        <span className="text-sm text-slate-500">
          Backfill: re-runs every enabled rule across your transaction history. Categories you set by hand are kept.
        </span>
      </div>

      {/* Packs */}
      {packs.map((pack) => (
        <div key={pack.id} className={`mb-6 card ${pack.enabled ? '' : 'opacity-60'}`} data-reveal>
          <div className="px-4 py-3 border-b border-white/[0.06] flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <div>
              <span className="font-display font-semibold text-slate-100">{pack.name}</span>
              {pack.imported_from && <span className="ml-2 chip-info">imported</span>}
              {pack.share_code && <span className="ml-2 chip-pos">shared</span>}
              {pack.description && <div className="text-sm text-slate-500">{pack.description}</div>}
            </div>
            <div className="flex flex-wrap gap-3 text-sm">
              <button onClick={() => setShowAddRule({ packId: pack.id })} className="btn-link">
                + Add rule
              </button>
              {pack.share_code ? (
                <>
                  <button onClick={() => sharePack(pack)} className="text-slate-400 hover:text-accent transition-colors">Copy link</button>
                  <button onClick={() => unsharePack(pack)} className="text-slate-400 hover:text-neg transition-colors">Unshare</button>
                </>
              ) : (
                <button onClick={() => sharePack(pack)} className="text-slate-400 hover:text-accent transition-colors">Share</button>
              )}
              <button onClick={() => togglePack(pack)} className="text-slate-400 hover:text-accent transition-colors">
                {pack.enabled ? 'Disable' : 'Enable'}
              </button>
              <button onClick={() => deletePack(pack)} className="text-slate-500 hover:text-neg transition-colors">Delete</button>
            </div>
          </div>
          <RuleList rules={pack.rules} onToggle={toggleRule} onDelete={deleteRule} />
        </div>
      ))}

      {/* Personal (learned + loose manual) rules */}
      <div className="mb-6 card" data-reveal>
        <div className="px-4 py-3 border-b border-white/[0.06]">
          <span className="font-display font-semibold text-slate-100">Personal rules</span>
          <div className="text-sm text-slate-500">
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
          onAdded={async (result) => {
            setShowAddRule(null)
            if (result?.applied) {
              setMessage(`Rule added — recategorized ${result.changed} transaction${result.changed !== 1 ? 's' : ''}.`)
            }
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
    return <div className="p-4 text-sm text-slate-600">No rules yet.</div>
  }
  return (
    <div className="divide-y divide-white/[0.06]">
      {rules.map((r) => (
        <div key={r.id} className={`p-3 px-4 flex items-center justify-between gap-3 ${r.enabled ? '' : 'opacity-50'}`}>
          <div className="min-w-0 text-sm">
            <span className="text-slate-500">{FIELD_LABEL[r.match_field]} {MATCH_TYPE_LABEL[r.match_type]} </span>
            <span className="font-mono font-medium text-slate-200 break-all">{r.pattern}</span>
            <span className="text-slate-500"> → </span>
            <span className="chip">{r.category}</span>
            {r.source === 'learned' && <span className="ml-1 text-xs text-slate-600">(learned)</span>}
          </div>
          <div className="flex gap-3 text-sm whitespace-nowrap">
            <button onClick={() => onToggle(r)} className="text-slate-400 hover:text-accent transition-colors">
              {r.enabled ? 'Disable' : 'Enable'}
            </button>
            <button onClick={() => onDelete(r)} className="text-slate-500 hover:text-neg transition-colors">
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
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-1">New pack</h3>
        <p className="text-sm text-slate-400 mb-4">A named set of rules you can share as one link.</p>
        <div className="space-y-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name (e.g. UK Essentials)"
            className="input"
            autoFocus
          />
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description (optional)"
            className="input"
          />
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={save} disabled={saving || !name.trim()} className="btn-primary">
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
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-1">Import a rule pack</h3>
        <p className="text-sm text-slate-400 mb-4">
          Paste a share link or code. You get your own copy — the author can't change it afterwards.
        </p>

        <div className="flex gap-2">
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="https://…/r/AB12CD or AB12CD"
            className="input flex-1"
            autoFocus
          />
          <button onClick={lookup} disabled={busy || !code.trim()} className="btn-ghost">
            Look up
          </button>
        </div>

        {error && <div className="banner-err mt-3 !p-2">{error}</div>}

        {preview && (
          <div className="mt-4 bg-white/[0.04] border border-white/[0.06] rounded-xl p-3">
            <div className="font-medium text-slate-200">{preview.name}</div>
            {preview.description && <div className="text-sm text-slate-500">{preview.description}</div>}
            <div className="text-sm text-slate-400 mt-1">{preview.rule_count} rules</div>
            <ul className="mt-2 text-xs text-slate-500 space-y-0.5 max-h-32 overflow-y-auto">
              {preview.rules.map((r: any, i: number) => (
                <li key={i} className="truncate">
                  <span className="font-mono">{r.pattern}</span> → {r.category}
                </li>
              ))}
            </ul>
            {preview.already_owned && (
              <div className="mt-2 text-xs text-warn">This is your own pack.</div>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={doImport} disabled={busy || !preview || preview.already_owned} className="btn-primary">
            {busy ? 'Importing…' : 'Import pack'}
          </button>
        </div>
      </div>
    </div>
  )
}

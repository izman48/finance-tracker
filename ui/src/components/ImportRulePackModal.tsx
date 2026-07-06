import { useEffect, useState } from 'react'
import { rulesAPI } from '../services/api'

export default function ImportRulePackModal({
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

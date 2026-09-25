import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import axios from 'axios'
import AuthShell from '../components/ui/AuthShell'
import { useAuth } from '../hooks/useAuth'
import { oauthApi, OAuthRequestDetails } from '../services/api'

const READ = 'finance:read'
const RULES_WRITE = 'finance:rules.write'

type ApiError = { error_description?: string; redirect_to?: string }

function errorOf(err: unknown): ApiError {
  return axios.isAxiosError(err) ? ((err.response?.data as ApiError) ?? {}) : {}
}

/**
 * Consent for a remote MCP client (Claude Code, Claude Desktop, …) — the
 * OAuth authorization endpoint. Approving here, with the web session, is the
 * one moment the server can hand the client access to the user's encrypted
 * data, so this page is the only way a connection is ever created.
 */
export default function OAuthConsentPage() {
  const [searchParams] = useSearchParams()
  const params = useMemo(() => Object.fromEntries(searchParams.entries()), [searchParams])
  const { user } = useAuth()

  const [details, setDetails] = useState<OAuthRequestDetails | null>(null)
  const [error, setError] = useState('')
  const [allowRules, setAllowRules] = useState(true)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    oauthApi
      .details(params)
      .then((res) => setDetails(res.data))
      .catch((err) => {
        const body = errorOf(err)
        // Once the client and its redirect are verified, errors go back to
        // the client (RFC 6749); before that we must never redirect.
        if (body.redirect_to) window.location.replace(body.redirect_to)
        else setError(body.error_description || 'This connection request is invalid.')
      })
  }, [params])

  const decide = async (approve: boolean) => {
    setBusy(true)
    setError('')
    try {
      const scopes = allowRules ? [READ, RULES_WRITE] : [READ]
      const res = await oauthApi.decide(params, approve, scopes)
      window.location.assign(res.data.redirect_to)
    } catch (err) {
      setError(errorOf(err).error_description || 'Could not complete the connection. Try again.')
      setBusy(false)
    }
  }

  if (error && !details) {
    return (
      <AuthShell title="Can't connect" subtitle="Start the connection again from your app.">
        <div className="banner-err">{error}</div>
      </AuthShell>
    )
  }

  if (!details) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-accent" />
      </div>
    )
  }

  return (
    <AuthShell
      title={`Connect ${details.client_name}`}
      subtitle="An AI assistant is asking to use your nilu. data."
    >
      <div className="space-y-5">
        {error && <div className="banner-err">{error}</div>}

        {user && (
          <p className="text-sm text-slate-400">
            Signed in as <span className="text-slate-200 break-all">{user.email}</span>
          </p>
        )}

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
              onChange={(e) => setAllowRules(e.target.checked)}
              className="mt-1 shrink-0 accent-accent"
            />
            <label htmlFor="allow-rules" className="min-w-0 cursor-pointer">
              <span className="block text-sm text-slate-100">Add rule packs</span>
              <span className="block text-xs text-slate-400">
                Create new categorisation rule packs. It can't edit or delete anything, and you can remove a pack in Rules.
              </span>
            </label>
          </li>
        </ul>

        <p className="text-xs text-slate-500">
          Whatever it reads is sent to the AI model you're using. You'll return to{' '}
          <span className="text-slate-300 break-all">{details.redirect_host}</span>. It stays connected while
          you use it; changing your password disconnects it.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <button type="button" className="btn-ghost w-full" disabled={busy} onClick={() => decide(false)}>
            Deny
          </button>
          <button type="button" className="btn-primary w-full" disabled={busy} onClick={() => decide(true)}>
            {busy ? 'Connecting…' : 'Allow'}
          </button>
        </div>
      </div>
    </AuthShell>
  )
}

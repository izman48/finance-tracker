import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { CheckCircle2, Loader2, XCircle } from 'lucide-react'

export default function CallbackPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading')
  const [message, setMessage] = useState('Processing bank connection...')

  useEffect(() => {
    // The OAuth code exchange is handled server-side by /banking/callback, which
    // TrueLayer redirects to directly and then forwards to /dashboard. This page
    // is only a fallback (e.g. a stale redirect_uri pointing at the frontend):
    // it surfaces any error and sends the user on to the dashboard.
    const error = searchParams.get('error')

    if (error) {
      setStatus('error')
      setMessage(`Authorization failed: ${error}`)
      setTimeout(() => navigate('/dashboard?bank_connected=false'), 3000)
      return
    }

    setStatus('success')
    setMessage('Bank connection processed! Redirecting to dashboard...')
    setTimeout(() => navigate('/dashboard?bank_connected=true'), 1500)
  }, [searchParams, navigate])

  return (
    <div className="min-h-[70vh] flex items-center justify-center px-4">
      <div className="max-w-md w-full card p-8 text-center animate-fade-up">
        {status === 'loading' && <Loader2 className="animate-spin h-12 w-12 mx-auto text-accent mb-4" />}
        {status === 'success' && <CheckCircle2 className="h-12 w-12 mx-auto text-pos mb-4" />}
        {status === 'error' && <XCircle className="h-12 w-12 mx-auto text-neg mb-4" />}

        <h2
          className={`font-display text-xl font-semibold mb-2 ${
            status === 'success' ? 'text-pos' : status === 'error' ? 'text-neg' : 'text-slate-100'
          }`}
        >
          {status === 'loading' && 'Connecting your bank'}
          {status === 'success' && 'Success!'}
          {status === 'error' && 'Connection failed'}
        </h2>

        <p className="text-slate-400">{message}</p>

        {status === 'error' && (
          <button onClick={() => navigate('/dashboard')} className="btn-primary mt-6">
            Return to dashboard
          </button>
        )}
      </div>
    </div>
  )
}

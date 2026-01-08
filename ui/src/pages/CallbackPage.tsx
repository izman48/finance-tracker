import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { bankingAPI } from '../services/api'

export default function CallbackPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading')
  const [message, setMessage] = useState('Processing bank connection...')

  useEffect(() => {
    const handleCallback = async () => {
      const code = searchParams.get('code')
      const error = searchParams.get('error')

      // Check for OAuth errors
      if (error) {
        setStatus('error')
        setMessage(`Authorization failed: ${error}`)
        setTimeout(() => navigate('/dashboard?bank_connected=false'), 3000)
        return
      }

      // Check for authorization code
      if (!code) {
        setStatus('error')
        setMessage('No authorization code received')
        setTimeout(() => navigate('/dashboard?bank_connected=false'), 3000)
        return
      }

      try {
        // Exchange code for tokens via backend
        setMessage('Exchanging authorization code...')
        await bankingAPI.exchangeOAuthCode(code)

        setStatus('success')
        setMessage('Bank connected successfully! Redirecting to dashboard...')

        // Redirect to dashboard after success
        setTimeout(() => {
          navigate('/dashboard?bank_connected=true')
        }, 2000)
      } catch (err: any) {
        console.error('Failed to exchange OAuth code:', err)
        setStatus('error')
        setMessage(
          err.response?.data?.detail || 'Failed to connect bank. Please try again.'
        )
        setTimeout(() => navigate('/dashboard?bank_connected=false'), 3000)
      }
    }

    handleCallback()
  }, [searchParams, navigate])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="max-w-md w-full p-8 bg-white rounded-xl shadow-lg">
        <div className="text-center">
          {/* Loading Spinner */}
          {status === 'loading' && (
            <div className="mb-4">
              <svg
                className="animate-spin h-12 w-12 mx-auto text-blue-600"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                ></circle>
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                ></path>
              </svg>
            </div>
          )}

          {/* Success Icon */}
          {status === 'success' && (
            <div className="mb-4">
              <svg
                className="h-12 w-12 mx-auto text-green-600"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                ></path>
              </svg>
            </div>
          )}

          {/* Error Icon */}
          {status === 'error' && (
            <div className="mb-4">
              <svg
                className="h-12 w-12 mx-auto text-red-600"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"
                ></path>
              </svg>
            </div>
          )}

          {/* Message */}
          <h2
            className={`text-xl font-semibold mb-2 ${
              status === 'success'
                ? 'text-green-800'
                : status === 'error'
                ? 'text-red-800'
                : 'text-gray-800'
            }`}
          >
            {status === 'loading' && 'Connecting Your Bank'}
            {status === 'success' && 'Success!'}
            {status === 'error' && 'Connection Failed'}
          </h2>

          <p className="text-gray-600">{message}</p>

          {status === 'error' && (
            <button
              onClick={() => navigate('/dashboard')}
              className="mt-6 px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              Return to Dashboard
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

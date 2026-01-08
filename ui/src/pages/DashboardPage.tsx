import { useEffect, useState } from 'react'
import { useAuth } from '../hooks/useAuth'
import { bankingAPI } from '../services/api'

interface BankConnection {
  id: string
  provider_name: string
  is_expired: boolean
  expires_at: string | null
}

interface BankStatus {
  is_connected: boolean
  connections_count: number
  connections: BankConnection[]
  message: string
}

interface Account {
  id: string
  provider_name: string
  account_type: string
  display_name: string
  currency: string
  current_balance: number | null
  available_balance: number | null
  balance_updated_at: string | null
}

export default function DashboardPage() {
  const { user } = useAuth()
  const [bankStatus, setBankStatus] = useState<BankStatus | null>(null)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    loadBankStatus()
    loadAccounts()

    // Check if we just returned from a successful bank connection
    const params = new URLSearchParams(window.location.search)
    const bankConnected = params.get('bank_connected')

    if (bankConnected === 'true') {
      setMessage('Bank connected successfully! Historical data has been synced automatically.')
      // Don't auto-sync here - the backend OAuth callback already synced 730 days of data
      // Just reload to show the new accounts and transactions
      loadAccounts()
      // Clean up URL
      window.history.replaceState({}, '', '/dashboard')
    } else if (bankConnected === 'false') {
      setMessage('Failed to connect bank. Please try again.')
      window.history.replaceState({}, '', '/dashboard')
    }
  }, [])

  const loadBankStatus = async () => {
    try {
      const response = await bankingAPI.getConnectionStatus()
      setBankStatus(response.data)
    } catch (error) {
      console.error('Failed to load bank status:', error)
    }
  }

  const loadAccounts = async () => {
    try {
      const response = await bankingAPI.getAccounts()
      setAccounts(response.data)
    } catch (error) {
      console.error('Failed to load accounts:', error)
    }
  }

  const handleConnectBank = async () => {
    setLoading(true)
    setMessage('')
    try {
      const response = await bankingAPI.getBankConnectionURL()
      const authUrl = response.data.auth_url
      // Redirect to TrueLayer authorization
      window.location.href = authUrl
    } catch (error: any) {
      setMessage('Failed to get bank connection URL: ' + (error.response?.data?.detail || error.message))
      setLoading(false)
    }
  }

  const handleSyncAccounts = async () => {
    setSyncing(true)
    setMessage('')
    try {
      const response = await bankingAPI.syncAccounts()
      setMessage(response.data.message)
      setAccounts(response.data.accounts)

      // Auto-sync transactions after accounts
      await handleSyncTransactions()
    } catch (error: any) {
      setMessage('Failed to sync accounts: ' + (error.response?.data?.detail || error.message))
    } finally {
      setSyncing(false)
    }
  }

  const handleSyncTransactions = async () => {
    setSyncing(true)
    try {
      // Request 730 days (2 years) - will fallback to 90 days if unavailable
      const response = await bankingAPI.syncTransactions(730)
      setMessage(response.data.message)
    } catch (error: any) {
      setMessage('Failed to sync transactions: ' + (error.response?.data?.detail || error.message))
    } finally {
      setSyncing(false)
    }
  }

  const handleDisconnectAllBanks = async () => {
    if (!confirm('Are you sure you want to disconnect ALL banks? This will delete all accounts and transactions.')) {
      return
    }

    setLoading(true)
    setMessage('')
    try {
      const response = await bankingAPI.disconnectAllBanks()
      setMessage(response.data.message)
      setBankStatus(null)
      setAccounts([])
      // Reload status
      await loadBankStatus()
    } catch (error: any) {
      setMessage('Failed to disconnect banks: ' + (error.response?.data?.detail || error.message))
    } finally {
      setLoading(false)
    }
  }

  const handleDisconnectSpecificBank = async (connectionId: string, providerName: string) => {
    console.log('Disconnect button clicked for:', connectionId, providerName)

    // Bypass confirm dialog - proceed directly
    console.log('Proceeding with disconnect, calling API...')
    setLoading(true)
    setMessage('')
    try {
      console.log('Calling bankingAPI.disconnectBank with:', connectionId)
      const response = await bankingAPI.disconnectBank(connectionId)
      console.log('Disconnect response:', response.data)
      setMessage(response.data.message)
      // Reload status and accounts
      await loadBankStatus()
      await loadAccounts()
    } catch (error: any) {
      console.error('Disconnect error:', error)
      setMessage('Failed to disconnect bank: ' + (error.response?.data?.detail || error.message))
    } finally {
      setLoading(false)
    }
  }

  const formatCurrency = (amount: number | null, currency: string = 'GBP') => {
    if (amount === null) return 'N/A'
    return new Intl.NumberFormat('en-GB', {
      style: 'currency',
      currency: currency,
    }).format(amount)
  }

  const formatDate = (date: string | null) => {
    if (!date) return 'Never'
    return new Date(date).toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold mb-8">Dashboard</h1>

      {/* Status Message */}
      {message && (
        <div className={`mb-6 p-4 rounded-lg ${
          message.includes('Failed') || message.includes('error')
            ? 'bg-red-100 text-red-800'
            : 'bg-green-100 text-green-800'
        }`}>
          {message}
        </div>
      )}

      {/* Bank Connections */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-2xl font-semibold">Connected Banks</h2>
          <div className="flex gap-2">
            <button
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              onClick={handleConnectBank}
              disabled={loading}
            >
              {loading ? 'Connecting...' : 'Connect Another Bank'}
            </button>
            {bankStatus?.is_connected && (
              <>
                <button
                  className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
                  onClick={handleSyncAccounts}
                  disabled={syncing}
                >
                  {syncing ? 'Syncing...' : 'Sync All'}
                </button>
                <button
                  className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
                  onClick={handleDisconnectAllBanks}
                  disabled={loading || syncing}
                >
                  Disconnect All
                </button>
              </>
            )}
          </div>
        </div>

        {bankStatus?.connections && bankStatus.connections.length > 0 ? (
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {bankStatus.connections.map((conn) => (
              <div key={conn.id} className="p-6 bg-white rounded-xl shadow-sm border border-gray-200">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="font-semibold text-lg">{conn.provider_name}</h3>
                    <p className={`text-sm mt-1 ${conn.is_expired ? 'text-red-600' : 'text-green-600'}`}>
                      {conn.is_expired ? 'Token Expired' : 'Active'}
                    </p>
                    {conn.expires_at && (
                      <p className="text-xs text-gray-500 mt-1">
                        Expires: {formatDate(conn.expires_at)}
                      </p>
                    )}
                  </div>
                  <button
                    onClick={() => handleDisconnectSpecificBank(conn.id, conn.provider_name)}
                    disabled={loading}
                    className="text-red-600 hover:text-red-800 text-sm disabled:opacity-50"
                  >
                    Disconnect
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 bg-white rounded-xl shadow-sm text-center text-gray-500">
            No banks connected. Click "Connect Another Bank" to get started.
          </div>
        )}
      </div>

      {/* Accounts */}
      {accounts.length > 0 && (
        <div className="mb-8">
          <h2 className="text-2xl font-semibold mb-4">Your Accounts</h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {accounts.map((account) => (
              <div key={account.id} className="p-6 bg-white rounded-xl shadow-sm border border-gray-200">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="font-semibold text-lg">{account.display_name}</h3>
                    <p className="text-sm text-gray-500">{account.provider_name}</p>
                  </div>
                  <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded">
                    {account.account_type}
                  </span>
                </div>
                <div className="space-y-2">
                  <div>
                    <p className="text-sm text-gray-600">Current Balance</p>
                    <p className="text-2xl font-bold">
                      {formatCurrency(account.current_balance, account.currency)}
                    </p>
                  </div>
                  {account.available_balance !== null && (
                    <div>
                      <p className="text-xs text-gray-500">Available</p>
                      <p className="text-sm font-semibold">
                        {formatCurrency(account.available_balance, account.currency)}
                      </p>
                    </div>
                  )}
                  <p className="text-xs text-gray-400 mt-2">
                    Updated: {formatDate(account.balance_updated_at)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty State */}
      {!bankStatus?.is_connected && accounts.length === 0 && (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Placeholder Cards */}
          <div className="p-6 bg-white rounded-xl shadow-sm">
            <h2 className="text-xl font-semibold mb-4">Spending Overview</h2>
            <p className="text-gray-500 text-sm">
              No data yet. Connect a bank account to see your spending.
            </p>
          </div>

          <div className="p-6 bg-white rounded-xl shadow-sm">
            <h2 className="text-xl font-semibold mb-4">Recurring Payments</h2>
            <p className="text-gray-500 text-sm">
              No recurring payments detected yet.
            </p>
          </div>

          <div className="p-6 bg-white rounded-xl shadow-sm">
            <h2 className="text-xl font-semibold mb-4">Opportunity Cost</h2>
            <p className="text-gray-500 text-sm">
              Connect your bank to see investment opportunities.
            </p>
          </div>
        </div>
      )}

      {/* Debug Info */}
      <div className="mt-8 p-6 bg-gray-100 rounded-xl">
        <h2 className="text-lg font-semibold mb-2">Debug Info</h2>
        <p className="text-sm text-gray-600">
          Logged in as: <strong>{user?.email}</strong>
        </p>
        <p className="text-sm text-gray-600">
          User ID: <code className="bg-gray-200 px-1 rounded">{user?.id}</code>
        </p>
        <p className="text-sm text-gray-600">
          Accounts: <strong>{accounts.length}</strong>
        </p>
      </div>
    </div>
  )
}

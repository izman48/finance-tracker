import { useEffect, useState } from 'react'
import { bankingAPI } from '../services/api'

interface Transaction {
  id: string
  transaction_type: string
  amount: number
  category: string | null
  merchant_name: string | null
  transaction_date: string
}

interface CategorySpending {
  category: string
  total: number
  count: number
  percentage: number
}

interface MonthlySpending {
  month: string
  total: number
}

export default function InsightsPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadAllTransactions()
  }, [])

  const loadAllTransactions = async () => {
    setLoading(true)
    try {
      // Load transactions in batches to avoid validation issues
      let allTransactions: Transaction[] = []
      let page = 1
      const pageSize = 100

      while (true) {
        const response = await bankingAPI.getTransactions({ page, page_size: pageSize })
        const items = response.data.items || []
        allTransactions = [...allTransactions, ...items]

        // Stop if we got fewer items than requested (last page) or have enough for analysis
        if (items.length < pageSize || allTransactions.length >= 2000) {
          break
        }
        page++
      }

      console.log(`Loaded ${allTransactions.length} transactions for insights`)
      setTransactions(allTransactions)
    } catch (error) {
      console.error('Failed to load transactions:', error)
    } finally {
      setLoading(false)
    }
  }

  // Calculate category breakdown
  const categoryBreakdown: CategorySpending[] = (() => {
    const categoryMap = new Map<string, { total: number; count: number }>()

    const debits = transactions.filter(tx => tx.transaction_type === 'debit')
    const totalSpent = debits.reduce((sum, tx) => sum + tx.amount, 0)

    debits.forEach(tx => {
      const category = tx.category || 'Uncategorized'
      const existing = categoryMap.get(category) || { total: 0, count: 0 }
      categoryMap.set(category, {
        total: existing.total + tx.amount,
        count: existing.count + 1,
      })
    })

    return Array.from(categoryMap.entries())
      .map(([category, data]) => ({
        category,
        total: data.total,
        count: data.count,
        percentage: (data.total / totalSpent) * 100,
      }))
      .sort((a, b) => b.total - a.total)
  })()

  // Calculate monthly spending
  const monthlyBreakdown: MonthlySpending[] = (() => {
    const monthMap = new Map<string, number>()

    transactions
      .filter(tx => tx.transaction_type === 'debit')
      .forEach(tx => {
        const date = new Date(tx.transaction_date)
        const monthKey = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
        const monthName = date.toLocaleDateString('en-GB', { year: 'numeric', month: 'short' })

        const existing = monthMap.get(monthName) || 0
        monthMap.set(monthName, existing + tx.amount)
      })

    return Array.from(monthMap.entries())
      .map(([month, total]) => ({ month, total }))
      .reverse() // Show all months, most recent first
  })()

  // Top merchants by total spend
  const topMerchants = (() => {
    const merchantMap = new Map<string, number>()

    transactions
      .filter(tx => tx.transaction_type === 'debit')
      .forEach(tx => {
        // Use merchant_name if available, otherwise use description
        const merchant = tx.merchant_name || tx.description
        if (merchant) {
          const existing = merchantMap.get(merchant) || 0
          merchantMap.set(merchant, existing + tx.amount)
        }
      })

    return Array.from(merchantMap.entries())
      .map(([merchant, total]) => ({ merchant, total }))
      .sort((a, b) => b.total - a.total)
      .slice(0, 10)
  })()

  // Most frequent merchants by transaction count
  const frequentMerchants = (() => {
    const merchantMap = new Map<string, { count: number; total: number }>()

    transactions
      .filter(tx => tx.transaction_type === 'debit')
      .forEach(tx => {
        const merchant = tx.merchant_name || tx.description
        if (merchant) {
          const existing = merchantMap.get(merchant) || { count: 0, total: 0 }
          merchantMap.set(merchant, {
            count: existing.count + 1,
            total: existing.total + tx.amount,
          })
        }
      })

    return Array.from(merchantMap.entries())
      .map(([merchant, data]) => ({
        merchant,
        count: data.count,
        average: data.total / data.count,
        total: data.total,
      }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 10)
  })()

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-GB', {
      style: 'currency',
      currency: 'GBP',
    }).format(amount)
  }

  const totalSpent = transactions
    .filter(tx => tx.transaction_type === 'debit')
    .reduce((sum, tx) => sum + tx.amount, 0)

  const avgTransaction = transactions.filter(tx => tx.transaction_type === 'debit').length > 0
    ? totalSpent / transactions.filter(tx => tx.transaction_type === 'debit').length
    : 0

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="text-center py-12">
          <div className="text-gray-600">Loading insights...</div>
        </div>
      </div>
    )
  }

  if (transactions.length === 0) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="text-center py-12">
          <div className="text-gray-600">No transactions yet. Sync your accounts to see insights.</div>
          <div className="text-xs text-gray-400 mt-2">Debug: transactions array length is {transactions.length}</div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold mb-6">Spending Insights</h1>

      {/* Overview Stats */}
      <div className="grid md:grid-cols-3 gap-4 mb-8">
        <div className="p-6 bg-white rounded-lg shadow-sm">
          <div className="text-sm text-gray-600 mb-1">Total Spent</div>
          <div className="text-3xl font-bold text-gray-900">{formatCurrency(totalSpent)}</div>
        </div>
        <div className="p-6 bg-white rounded-lg shadow-sm">
          <div className="text-sm text-gray-600 mb-1">Transactions</div>
          <div className="text-3xl font-bold text-gray-900">
            {transactions.filter(tx => tx.transaction_type === 'debit').length}
          </div>
        </div>
        <div className="p-6 bg-white rounded-lg shadow-sm">
          <div className="text-sm text-gray-600 mb-1">Avg Transaction</div>
          <div className="text-3xl font-bold text-gray-900">{formatCurrency(avgTransaction)}</div>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        {/* Category Breakdown */}
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h2 className="text-xl font-semibold mb-4">Spending by Category</h2>
          <div className="space-y-3">
            {categoryBreakdown.map((cat) => (
              <div key={cat.category}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-gray-700">{cat.category}</span>
                  <span className="text-sm font-semibold text-gray-900">
                    {formatCurrency(cat.total)}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="flex-1 bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-blue-600 h-2 rounded-full"
                      style={{ width: `${cat.percentage}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-500 w-12 text-right">
                    {cat.percentage.toFixed(1)}%
                  </span>
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  {cat.count} transaction{cat.count !== 1 ? 's' : ''}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Monthly Trend */}
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h2 className="text-xl font-semibold mb-4">Monthly Spending</h2>
          <div className="space-y-3">
            {monthlyBreakdown.map((month) => (
              <div key={month.month} className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-700">{month.month}</span>
                <span className="text-sm font-semibold text-gray-900">
                  {formatCurrency(month.total)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Top Merchants by Total Spend */}
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h2 className="text-xl font-semibold mb-4">Top Merchants (by spend)</h2>
          <div className="space-y-3">
            {topMerchants.map((merchant, index) => (
              <div key={merchant.merchant} className="flex items-center gap-3">
                <div className="w-6 h-6 flex items-center justify-center bg-gray-100 rounded-full text-xs font-bold text-gray-600">
                  {index + 1}
                </div>
                <div className="flex-1">
                  <div className="text-sm font-medium text-gray-900">{merchant.merchant}</div>
                </div>
                <div className="text-sm font-semibold text-gray-900">
                  {formatCurrency(merchant.total)}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Most Frequent Merchants */}
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h2 className="text-xl font-semibold mb-4">Most Frequent Merchants</h2>
          <div className="space-y-3">
            {frequentMerchants.map((merchant, index) => (
              <div key={merchant.merchant} className="flex items-center gap-3">
                <div className="w-6 h-6 flex items-center justify-center bg-blue-100 rounded-full text-xs font-bold text-blue-600">
                  {index + 1}
                </div>
                <div className="flex-1">
                  <div className="text-sm font-medium text-gray-900">{merchant.merchant}</div>
                  <div className="text-xs text-gray-500">
                    {merchant.count} transaction{merchant.count !== 1 ? 's' : ''} · Avg {formatCurrency(merchant.average)}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-sm font-semibold text-gray-900">
                    {formatCurrency(merchant.total)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

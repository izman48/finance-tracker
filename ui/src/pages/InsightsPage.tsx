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
  const [allTransactions, setAllTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)

  // Filters
  const [startDate, setStartDate] = useState<string>('')
  const [endDate, setEndDate] = useState<string>('')
  const [selectedCategories, setSelectedCategories] = useState<string[]>([])
  const [hideInternalTransfers, setHideInternalTransfers] = useState<boolean>(false)

  useEffect(() => {
    loadAllTransactions()
  }, [])

  const loadAllTransactions = async () => {
    setLoading(true)
    try {
      // Load all transactions (up to 10000) for comprehensive insights
      let transactions: Transaction[] = []
      let page = 1
      const pageSize = 100

      while (transactions.length < 10000) {
        const response = await bankingAPI.getTransactions({ page, page_size: pageSize })
        const items = response.data.items || []
        transactions = [...transactions, ...items]

        // Stop if we got fewer items than requested (last page)
        if (items.length < pageSize) {
          break
        }
        page++
      }

      // Deduplicate transactions by ID (in case API returns duplicates)
      const uniqueTransactions = Array.from(
        new Map(transactions.map(tx => [tx.id, tx])).values()
      )

      console.log(`Loaded ${transactions.length} transactions, ${uniqueTransactions.length} unique for insights`)
      setAllTransactions(uniqueTransactions)
    } catch (error) {
      console.error('Failed to load transactions:', error)
    } finally {
      setLoading(false)
    }
  }

  // Get all unique categories for filter
  const allCategories = Array.from(new Set(
    allTransactions.map(tx => tx.category).filter(Boolean)
  )).sort()

  // Detect internal transfers (same amount, opposite type, within 2-day range, different accounts)
  let transactionsToFilter = allTransactions
  if (hideInternalTransfers) {
    const internalTransferIds = new Set<string>()

    // Sort transactions by date for efficient processing
    const sortedTxs = [...allTransactions].sort((a, b) =>
      new Date(a.transaction_date).getTime() - new Date(b.transaction_date).getTime()
    )

    // Find matching pairs within 2-day window
    for (let i = 0; i < sortedTxs.length; i++) {
      const tx1 = sortedTxs[i]
      const tx1Date = new Date(tx1.transaction_date)

      // Only look ahead at transactions within 2 days
      for (let j = i + 1; j < sortedTxs.length; j++) {
        const tx2 = sortedTxs[j]
        const tx2Date = new Date(tx2.transaction_date)

        // Calculate difference in days
        const daysDiff = Math.abs((tx2Date.getTime() - tx1Date.getTime()) / (1000 * 60 * 60 * 24))

        // Stop looking if we've gone beyond 2 days
        if (daysDiff > 2) {
          break
        }

        // Check if they're internal transfers:
        // 1. Same amount
        // 2. Opposite transaction types (one debit, one credit)
        // 3. Different accounts
        // 4. Within 2 days
        const sameAmount = Math.abs(tx1.amount - tx2.amount) < 0.01 // Allow for small rounding differences
        const oppositeTypes = (tx1.transaction_type === 'debit' && tx2.transaction_type === 'credit') ||
                              (tx1.transaction_type === 'credit' && tx2.transaction_type === 'debit')
        const differentAccounts = tx1.account_id !== tx2.account_id

        if (sameAmount && oppositeTypes && differentAccounts) {
          // Mark both as internal transfers to be filtered out
          internalTransferIds.add(tx1.id)
          internalTransferIds.add(tx2.id)
        }
      }
    }

    console.log(`Insights: Detected ${internalTransferIds.size} internal transfer transactions (within 2-day window)`)
    transactionsToFilter = allTransactions.filter(tx => !internalTransferIds.has(tx.id))
  }

  // Apply filters to transactions
  const transactions = transactionsToFilter.filter(tx => {
    const txDate = new Date(tx.transaction_date)
    const matchesStartDate = !startDate || txDate >= new Date(startDate)
    const matchesEndDate = !endDate || txDate <= new Date(endDate + 'T23:59:59')
    const matchesCategory = selectedCategories.length === 0 || selectedCategories.includes(tx.category || 'Uncategorized')
    return matchesStartDate && matchesEndDate && matchesCategory
  })

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
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Spending Insights</h1>
        <div className="text-sm text-gray-600">
          {allTransactions.length} total transactions
          {transactions.length !== allTransactions.length && (
            <span> ({transactions.length} filtered)</span>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white p-4 rounded-lg shadow-sm mb-6">
        <div className="grid md:grid-cols-3 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Start Date
            </label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              End Date
            </label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Categories (select multiple)
            </label>
            <div className="border border-gray-300 rounded-lg p-2 max-h-48 overflow-y-auto bg-white">
              {selectedCategories.length > 0 && (
                <div className="mb-2 pb-2 border-b border-gray-200">
                  <button
                    onClick={() => setSelectedCategories([])}
                    className="text-xs text-blue-600 hover:text-blue-800"
                  >
                    Clear all ({selectedCategories.length})
                  </button>
                </div>
              )}
              {['Uncategorized', ...allCategories].map(category => {
                const categoryValue = category === 'Uncategorized' ? 'Uncategorized' : category
                const isSelected = selectedCategories.includes(categoryValue)
                return (
                  <label key={category} className="flex items-center py-1 px-2 hover:bg-gray-50 rounded cursor-pointer">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedCategories([...selectedCategories, categoryValue])
                        } else {
                          setSelectedCategories(selectedCategories.filter(c => c !== categoryValue))
                        }
                      }}
                      className="mr-2"
                    />
                    <span className="text-sm">{category}</span>
                  </label>
                )
              })}
            </div>
          </div>
        </div>

        {/* Internal Transfers Toggle */}
        <div className="pt-4 border-t border-gray-200">
          <label className="flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={hideInternalTransfers}
              onChange={(e) => setHideInternalTransfers(e.target.checked)}
              className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500 focus:ring-2"
            />
            <span className="ml-2 text-sm text-gray-700">
              Hide internal transfers between accounts
            </span>
            <span className="ml-2 text-xs text-gray-500">
              (Filters out matching debit/credit pairs within 2 days)
            </span>
          </label>
        </div>

        <div className="flex justify-end mt-4">
          <button
            onClick={() => {
              setStartDate('')
              setEndDate('')
              setSelectedCategories([])
              setHideInternalTransfers(false)
            }}
            className="px-4 py-2 text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
          >
            Clear All Filters
          </button>
        </div>
      </div>

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
          <div className="space-y-3 max-h-96 overflow-y-auto">
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

import React, { useEffect, useState } from 'react'
import { ArrowDownToLine, ChevronDown, CreditCard, Repeat, SlidersHorizontal, Wand2 } from 'lucide-react'
import { bankingAPI, analyticsAPI } from '../services/api'
import AddRuleModal from '../components/AddRuleModal'

interface Transaction {
  id: string
  account_id: string
  transaction_type: string
  amount: number
  currency: string
  description: string
  merchant_name: string | null
  category: string | null
  subcategory: string | null
  is_recurring: boolean
  is_commitment: boolean
  is_financed: boolean
  transaction_date: string
}

interface Account {
  id: string
  display_name: string
  provider_name: string
  account_type: string
}

export default function TransactionsPage() {
  const [allTransactions, setAllTransactions] = useState<Transaction[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(50)
  const [editingTransactionId, setEditingTransactionId] = useState<string | null>(null)
  const [editingCategory, setEditingCategory] = useState<string>('')
  const [recurringTx, setRecurringTx] = useState<Transaction | null>(null)
  const [financeTx, setFinanceTx] = useState<Transaction | null>(null)
  const [ruleTx, setRuleTx] = useState<Transaction | null>(null)
  const [toast, setToast] = useState<string>('')
  const [customCategories, setCustomCategories] = useState<string[]>([])
  const [isAddingCategory, setIsAddingCategory] = useState(false)
  const [newCategoryName, setNewCategoryName] = useState('')
  const [sortField, setSortField] = useState<'date' | 'amount' | null>('date')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')

  // Bulk category update
  const [selectedTransactionIds, setSelectedTransactionIds] = useState<Set<string>>(new Set())
  const [isBulkCategoryMode, setIsBulkCategoryMode] = useState(false)
  const [bulkCategory, setBulkCategory] = useState<string>('')
  const [isBulkAddingCategory, setIsBulkAddingCategory] = useState(false)
  const [bulkNewCategoryName, setBulkNewCategoryName] = useState('')
  const [isUpdatingBulk, setIsUpdatingBulk] = useState(false)

  // Filters
  const [showFilters, setShowFilters] = useState(false)
  const [selectedAccount, setSelectedAccount] = useState<string>('')
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedCategories, setSelectedCategories] = useState<string[]>([])
  const [startDate, setStartDate] = useState<string>('')
  const [endDate, setEndDate] = useState<string>('')
  const [minAmount, setMinAmount] = useState<string>('')
  const [maxAmount, setMaxAmount] = useState<string>('')
  const [selectedMerchant, setSelectedMerchant] = useState<string>('')
  const [selectedType, setSelectedType] = useState<string>('')
  const [hideInternalTransfers, setHideInternalTransfers] = useState<boolean>(false)
  const [hideCreditCardPayments, setHideCreditCardPayments] = useState<boolean>(false)
  const [hideCommitments, setHideCommitments] = useState<boolean>(false)

  useEffect(() => {
    loadAccounts()
    loadAllTransactions()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refetch only when the account filter changes
  }, [selectedAccount])

  // Reset to page 1 when filters or sort changes
  useEffect(() => {
    setPage(1)
  }, [searchTerm, selectedCategories, startDate, endDate, minAmount, maxAmount, selectedMerchant, selectedType, hideInternalTransfers, hideCreditCardPayments, hideCommitments, sortField, sortDirection])

  const loadAccounts = async () => {
    try {
      const response = await bankingAPI.getAccounts()
      setAccounts(response.data)
    } catch (error) {
      console.error('Failed to load accounts:', error)
    }
  }

  const loadAllTransactions = async () => {
    setLoading(true)
    try {
      // Load all transactions (up to 10000) for client-side filtering and sorting
      let transactions: Transaction[] = []
      let currentPage = 1
      const fetchPageSize = 100

      while (transactions.length < 10000) {
        const params: any = { page: currentPage, page_size: fetchPageSize }
        if (selectedAccount) {
          params.account_id = selectedAccount
        }

        const response = await bankingAPI.getTransactions(params)
        const items = response.data.items || []
        transactions = [...transactions, ...items]

        // Stop if we got fewer items than requested (last page)
        if (items.length < fetchPageSize) break
        currentPage++
      }

      // Deduplicate transactions by ID (in case API returns duplicates)
      const uniqueTransactions = Array.from(
        new Map(transactions.map(tx => [tx.id, tx])).values()
      )

      setAllTransactions(uniqueTransactions)
    } catch (error) {
      console.error('Failed to load transactions:', error)
    } finally {
      setLoading(false)
    }
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-GB', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    })
  }

  const formatCurrency = (amount: number, currency: string = 'GBP') => {
    return new Intl.NumberFormat('en-GB', {
      style: 'currency',
      currency: currency,
    }).format(amount)
  }

  const getAccountName = (accountId: string) => {
    const account = accounts.find(a => a.id === accountId)
    return account ? account.display_name : 'Unknown Account'
  }

  const handleEditCategory = (transaction: Transaction) => {
    setEditingTransactionId(transaction.id)
    setEditingCategory(transaction.category || '')
    setIsAddingCategory(false)
    setNewCategoryName('')
  }

  const handleSaveCategory = async (transactionId: string) => {
    try {
      const response = await bankingAPI.updateTransaction(transactionId, {
        category: editingCategory || null
      })

      // Update the transaction in the local state
      setAllTransactions(allTransactions.map(tx =>
        tx.id === transactionId ? { ...tx, category: response.data.category } : tx
      ))

      setEditingTransactionId(null)
      setEditingCategory('')
    } catch (error) {
      console.error('Failed to update category:', error)
      alert('Failed to update category')
    }
  }

  const handleCancelEdit = () => {
    setEditingTransactionId(null)
    setEditingCategory('')
    setIsAddingCategory(false)
    setNewCategoryName('')
  }

  const handleAddCustomCategory = () => {
    if (newCategoryName.trim()) {
      setCustomCategories([...customCategories, newCategoryName.trim()])
      setEditingCategory(newCategoryName.trim())
      setIsAddingCategory(false)
      setNewCategoryName('')
    }
  }

  const handleToggleTransaction = (transactionId: string) => {
    const newSelected = new Set(selectedTransactionIds)
    if (newSelected.has(transactionId)) {
      newSelected.delete(transactionId)
    } else {
      newSelected.add(transactionId)
    }
    setSelectedTransactionIds(newSelected)
  }

  const handleSelectAll = () => {
    // Select ALL filtered transactions (across all pages)
    const newSelected = new Set<string>()
    filteredAndSortedTransactions.forEach(tx => newSelected.add(tx.id))
    setSelectedTransactionIds(newSelected)
  }

  const handleDeselectAll = () => {
    setSelectedTransactionIds(new Set())
  }

  const handleAddBulkCustomCategory = () => {
    if (bulkNewCategoryName.trim()) {
      setCustomCategories([...customCategories, bulkNewCategoryName.trim()])
      setBulkCategory(bulkNewCategoryName.trim())
      setIsBulkAddingCategory(false)
      setBulkNewCategoryName('')
    }
  }

  const handleBulkUpdateCategory = async () => {
    if (selectedTransactionIds.size === 0) {
      alert('Please select at least one transaction')
      return
    }

    setIsUpdatingBulk(true)
    try {
      // Update all selected transactions
      const updates = Array.from(selectedTransactionIds).map(id =>
        bankingAPI.updateTransaction(id, {
          category: bulkCategory || null
        })
      )

      await Promise.all(updates)

      // Update local state
      setAllTransactions(allTransactions.map(tx =>
        selectedTransactionIds.has(tx.id)
          ? { ...tx, category: bulkCategory || null }
          : tx
      ))

      // Reset bulk mode
      setIsBulkCategoryMode(false)
      setBulkCategory('')
      setSelectedTransactionIds(new Set())
      setIsBulkAddingCategory(false)
      setBulkNewCategoryName('')
    } catch (error) {
      console.error('Failed to update categories:', error)
      alert('Failed to update some transactions')
    } finally {
      setIsUpdatingBulk(false)
    }
  }

  const handleCancelBulkMode = () => {
    setIsBulkCategoryMode(false)
    setBulkCategory('')
    setSelectedTransactionIds(new Set())
    setIsBulkAddingCategory(false)
    setBulkNewCategoryName('')
  }

  const handleDownloadCSV = () => {
    // Create CSV header
    const headers = ['Date', 'Description', 'Merchant', 'Account', 'Category', 'Type', 'Amount', 'Currency']

    // Create CSV rows from filtered transactions
    const rows = filteredAndSortedTransactions.map(tx => [
      new Date(tx.transaction_date).toLocaleDateString('en-GB'),
      `"${(tx.description || '').replace(/"/g, '""')}"`, // Escape quotes
      `"${(tx.merchant_name || '').replace(/"/g, '""')}"`,
      `"${getAccountName(tx.account_id).replace(/"/g, '""')}"`,
      `"${(tx.category || 'Uncategorized').replace(/"/g, '""')}"`,
      tx.transaction_type,
      tx.amount.toFixed(2),
      tx.currency
    ])

    // Combine headers and rows
    const csvContent = [
      headers.join(','),
      ...rows.map(row => row.join(','))
    ].join('\n')

    // Create blob and download
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const link = document.createElement('a')
    const url = URL.createObjectURL(blob)

    link.setAttribute('href', url)
    link.setAttribute('download', `transactions_${new Date().toISOString().split('T')[0]}.csv`)
    link.style.visibility = 'hidden'

    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  // Filter and sort ALL transactions, then paginate client-side
  const filteredAndSortedTransactions = React.useMemo(() => {
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

      transactionsToFilter = allTransactions.filter(tx => !internalTransferIds.has(tx.id))
    }

    // Filter out credit card payments (both sides of the transaction)
    if (hideCreditCardPayments) {
      transactionsToFilter = transactionsToFilter.filter(tx => {
        // Find the account for this transaction
        const account = accounts.find(acc => acc.id === tx.account_id)

        // Case 1: If it's a credit card account and the transaction is a credit (payment TO the card), hide it
        if (account && account.account_type === 'CREDIT_CARD' && tx.transaction_type === 'credit') {
          return false // Hide credit card payments (receiving side)
        }

        // Case 2: If it's a debit from a non-credit-card account to pay a credit card
        // Look for "AMERICAN EXPRESS", "AMEX", credit card provider names in description
        if (account && account.account_type !== 'CREDIT_CARD' && tx.transaction_type === 'debit') {
          const description = (tx.description || '').toLowerCase()
          const merchantName = (tx.merchant_name || '').toLowerCase()

          // Common credit card payment indicators
          const creditCardPaymentIndicators = [
            'american express',
            'amex',
            'monzo flex',
            'barclaycard',
            'credit card payment',
            'cc payment'
          ]

          const isLikelyCreditCardPayment = creditCardPaymentIndicators.some(indicator =>
            description.includes(indicator) || merchantName.includes(indicator)
          )

          if (isLikelyCreditCardPayment) {
            return false // Hide payments from checking/savings accounts to credit cards
          }
        }

        return true // Keep everything else
      })
    }

    // Hide transactions that belong to confirmed commitments (rent, salary,
    // subscriptions…) — flagged by the API — to leave discretionary activity.
    if (hideCommitments) {
      transactionsToFilter = transactionsToFilter.filter(tx => !tx.is_commitment)
    }

    // First, filter ALL transactions (excluding internal transfers and credit card payments if enabled)
    const filtered = transactionsToFilter.filter(tx => {
      // Search filter (description or merchant name)
      const matchesSearch = searchTerm === '' ||
        tx.description?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        tx.merchant_name?.toLowerCase().includes(searchTerm.toLowerCase())

      // Category filter (multi-select)
      const matchesCategory = selectedCategories.length === 0 || selectedCategories.includes(tx.category || 'Uncategorized')

      // Type filter based on transaction_type field
      let matchesType = true
      if (selectedType === 'debit') {
        matchesType = tx.transaction_type === 'debit'
      } else if (selectedType === 'credit') {
        matchesType = tx.transaction_type === 'credit'
      }
      // If selectedType is empty string, matchesType stays true (show all)

      // Date range filtering
      const txDate = new Date(tx.transaction_date)
      const matchesStartDate = !startDate || txDate >= new Date(startDate)
      const matchesEndDate = !endDate || txDate <= new Date(endDate + 'T23:59:59')

      // Amount range filtering (use absolute value)
      const txAmount = Math.abs(tx.amount)
      const matchesMinAmount = !minAmount || txAmount >= parseFloat(minAmount)
      const matchesMaxAmount = !maxAmount || txAmount <= parseFloat(maxAmount)

      // Merchant filtering (use description if merchant_name is null)
      const merchant = tx.merchant_name || tx.description
      const matchesMerchant = !selectedMerchant || merchant === selectedMerchant

      return matchesSearch && matchesCategory && matchesType && matchesStartDate && matchesEndDate &&
             matchesMinAmount && matchesMaxAmount && matchesMerchant
    })

    // Then, sort if a sort field is selected
    if (!sortField) {
      return filtered
    }

    const sorted = [...filtered].sort((a, b) => {
      let comparison = 0

      if (sortField === 'date') {
        const dateA = new Date(a.transaction_date).getTime()
        const dateB = new Date(b.transaction_date).getTime()
        comparison = dateA - dateB

        // Handle invalid dates
        if (isNaN(comparison)) return 0
      } else if (sortField === 'amount') {
        const amountA = Math.abs(a.amount || 0)
        const amountB = Math.abs(b.amount || 0)
        comparison = amountA - amountB

        // Handle NaN values
        if (isNaN(comparison)) return 0
      }

      return sortDirection === 'asc' ? comparison : -comparison
    })

    return sorted
  }, [allTransactions, accounts, searchTerm, selectedCategories, selectedType, startDate, endDate, minAmount, maxAmount, selectedMerchant, hideInternalTransfers, hideCreditCardPayments, hideCommitments, sortField, sortDirection])

  // Get unique categories from all loaded transactions + custom ones
  const categories = Array.from(new Set([
    ...allTransactions.map(tx => tx.category).filter((c): c is string => Boolean(c)),
    ...customCategories
  ])).sort()

  // Get unique merchants from all loaded transactions
  const merchants = Array.from(new Set(
    allTransactions.map(tx => tx.merchant_name || tx.description).filter(Boolean)
  )).sort()

  // Apply client-side pagination to filtered/sorted results
  const totalFiltered = filteredAndSortedTransactions.length
  const totalPages = Math.ceil(totalFiltered / pageSize)
  const startIndex = (page - 1) * pageSize
  const endIndex = startIndex + pageSize
  const paginatedTransactions = filteredAndSortedTransactions.slice(startIndex, endIndex)

  // Calculate totals
  const totalSpent = filteredAndSortedTransactions
    .filter(tx => tx.transaction_type === 'debit')
    .reduce((sum, tx) => sum + tx.amount, 0)

  const totalIncome = filteredAndSortedTransactions
    .filter(tx => tx.transaction_type === 'credit')
    .reduce((sum, tx) => sum + tx.amount, 0)

  const activeFilterCount = [
    selectedCategories.length > 0,
    !!startDate,
    !!endDate,
    !!minAmount,
    !!maxAmount,
    !!selectedMerchant,
    !!selectedType,
    hideInternalTransfers,
    hideCreditCardPayments,
    hideCommitments,
  ].filter(Boolean).length

  const clearFilters = () => {
    setStartDate('')
    setEndDate('')
    setSearchTerm('')
    setSelectedCategories([])
    setSelectedAccount('')
    setMinAmount('')
    setMaxAmount('')
    setSelectedMerchant('')
    setSelectedType('')
    setHideInternalTransfers(false)
    setHideCreditCardPayments(false)
    setHideCommitments(false)
  }

  const renderCategoryEditor = (transaction: Transaction) =>
    editingTransactionId === transaction.id ? (
      <div className="flex items-center gap-2">
        <div className="flex-1">
          {isAddingCategory ? (
            <div className="flex items-center gap-1">
              <input
                type="text"
                value={newCategoryName}
                onChange={(e) => setNewCategoryName(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleAddCustomCategory()}
                placeholder="New category name"
                className="input !px-2 !py-1 !text-xs !rounded-lg"
                autoFocus
              />
              <button onClick={handleAddCustomCategory} className="btn-primary !px-2 !py-1 !text-xs !rounded-lg">
                Add
              </button>
              <button
                onClick={() => { setIsAddingCategory(false); setNewCategoryName('') }}
                className="btn-ghost !px-2 !py-1 !text-xs !rounded-lg"
              >
                Cancel
              </button>
            </div>
          ) : (
            <select
              value={editingCategory}
              onChange={(e) => {
                if (e.target.value === '__ADD_NEW__') {
                  setIsAddingCategory(true)
                } else {
                  setEditingCategory(e.target.value)
                }
              }}
              className="input !px-2 !py-1 !text-xs !rounded-lg"
              autoFocus
            >
              <option value="">Uncategorized</option>
              {categories.map(cat => (
                <option key={cat} value={cat}>
                  {cat}
                </option>
              ))}
              <option value="__ADD_NEW__">+ Add New Category</option>
            </select>
          )}
        </div>
        {!isAddingCategory && (
          <>
            <button
              onClick={() => handleSaveCategory(transaction.id)}
              className="btn-primary !px-2 !py-1 !text-xs !rounded-lg"
            >
              Save
            </button>
            <button onClick={handleCancelEdit} className="btn-ghost !px-2 !py-1 !text-xs !rounded-lg">
              Cancel
            </button>
          </>
        )}
      </div>
    ) : (
      <div onClick={() => handleEditCategory(transaction)} className="cursor-pointer group/cat">
        {transaction.category ? (
          <span className="chip group-hover/cat:bg-accent/15 group-hover/cat:text-accent transition-colors">
            {transaction.category}
          </span>
        ) : (
          <span className="text-xs text-slate-600 group-hover/cat:text-accent transition-colors">
            Click to categorize
          </span>
        )}
      </div>
    )

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 sm:py-10">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <div className="flex items-baseline gap-3">
          <h1 className="font-display font-bold text-2xl sm:text-3xl text-slate-50">Activity</h1>
          <span className="text-sm text-slate-500">{allTransactions.length} transactions</span>
        </div>
        <button
          onClick={handleDownloadCSV}
          disabled={filteredAndSortedTransactions.length === 0}
          className="btn-ghost"
          title={`Download ${filteredAndSortedTransactions.length} filtered transactions as CSV`}
        >
          <ArrowDownToLine className="w-4 h-4" />
          Download CSV
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="card p-4">
          <div className="text-sm text-slate-400 mb-1">Spent</div>
          <div className="stat-figure text-2xl text-neg">−{formatCurrency(totalSpent)}</div>
        </div>
        <div className="card p-4">
          <div className="text-sm text-slate-400 mb-1">Income</div>
          <div className="stat-figure text-2xl text-pos">+{formatCurrency(totalIncome)}</div>
        </div>
        <div className="card p-4">
          <div className="text-sm text-slate-400 mb-1">Net</div>
          <div className={`stat-figure text-2xl ${totalIncome - totalSpent >= 0 ? 'text-pos' : 'text-neg'}`}>
            {formatCurrency(totalIncome - totalSpent)}
          </div>
        </div>
      </div>

      {/* Search + filter bar */}
      <div className="card p-4 mb-6">
        <div className="flex flex-col md:flex-row gap-3">
          <input
            type="text"
            placeholder="Search description or merchant…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="input flex-1"
          />
          <select
            value={selectedAccount}
            onChange={(e) => setSelectedAccount(e.target.value)}
            className="input md:!w-56"
          >
            <option value="">All accounts</option>
            {accounts.map(account => (
              <option key={account.id} value={account.id}>
                {account.display_name}
              </option>
            ))}
          </select>
          <button
            onClick={() => setShowFilters((s) => !s)}
            className={`btn ${showFilters || activeFilterCount > 0 ? 'bg-accent/15 text-accent' : 'bg-white/[0.06] text-slate-200 hover:bg-white/[0.1]'}`}
            aria-expanded={showFilters}
          >
            <SlidersHorizontal className="w-4 h-4" />
            Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}
            <ChevronDown className={`w-4 h-4 transition-transform ${showFilters ? 'rotate-180' : ''}`} />
          </button>
        </div>

        {showFilters && (
          <div className="mt-4 pt-4 border-t border-white/[0.06]">
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
              <div>
                <label className="label">Start date</label>
                <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="input" />
              </div>
              <div>
                <label className="label">End date</label>
                <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="input" />
              </div>
              <div>
                <label className="label">Min amount</label>
                <input
                  type="number"
                  step="0.01"
                  placeholder="0.00"
                  value={minAmount}
                  onChange={(e) => setMinAmount(e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label className="label">Max amount</label>
                <input
                  type="number"
                  step="0.01"
                  placeholder="999999.99"
                  value={maxAmount}
                  onChange={(e) => setMaxAmount(e.target.value)}
                  className="input"
                />
              </div>
            </div>

            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-4">
              <div>
                <label className="label">Merchant</label>
                <select value={selectedMerchant} onChange={(e) => setSelectedMerchant(e.target.value)} className="input">
                  <option value="">All merchants</option>
                  {merchants.map(merchant => (
                    <option key={merchant} value={merchant}>
                      {merchant}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Type</label>
                <select value={selectedType} onChange={(e) => setSelectedType(e.target.value)} className="input">
                  <option value="">All transactions</option>
                  <option value="debit">Expenses only</option>
                  <option value="credit">Income only</option>
                </select>
              </div>
              <div>
                <label className="label">Categories</label>
                <div className="border border-white/10 rounded-xl p-2 max-h-40 overflow-y-auto bg-white/[0.03]">
                  {selectedCategories.length > 0 && (
                    <div className="mb-2 pb-2 border-b border-white/[0.06]">
                      <button onClick={() => setSelectedCategories([])} className="text-xs text-accent hover:text-accent-bright">
                        Clear all ({selectedCategories.length})
                      </button>
                    </div>
                  )}
                  {['Uncategorized', ...categories].map(category => {
                    const categoryValue = category === 'Uncategorized' ? 'Uncategorized' : category
                    const isSelected = selectedCategories.includes(categoryValue)
                    return (
                      <label key={category} className="flex items-center py-1 px-2 hover:bg-white/[0.04] rounded-lg cursor-pointer">
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
                          className="checkbox mr-2"
                        />
                        <span className="text-sm text-slate-300">{category}</span>
                      </label>
                    )
                  })}
                </div>
              </div>
            </div>

            <div className="space-y-3 mb-4">
              <label className="flex items-start sm:items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={hideInternalTransfers}
                  onChange={(e) => setHideInternalTransfers(e.target.checked)}
                  className="checkbox mt-0.5 sm:mt-0"
                />
                <span className="ml-2 text-sm text-slate-300">
                  Hide internal transfers between accounts
                  <span className="ml-1 text-xs text-slate-500">(matching debit/credit pairs within 2 days)</span>
                </span>
              </label>

              <label className="flex items-start sm:items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={hideCreditCardPayments}
                  onChange={(e) => setHideCreditCardPayments(e.target.checked)}
                  className="checkbox mt-0.5 sm:mt-0"
                />
                <span className="ml-2 text-sm text-slate-300">
                  Hide credit card payments
                  <span className="ml-1 text-xs text-slate-500">(keeps purchases made with the cards)</span>
                </span>
              </label>

              <label className="flex items-start sm:items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={hideCommitments}
                  onChange={(e) => setHideCommitments(e.target.checked)}
                  className="checkbox mt-0.5 sm:mt-0"
                />
                <span className="ml-2 text-sm text-slate-300">
                  Hide commitments
                  <span className="ml-1 text-xs text-slate-500">(rent, salary, subscriptions — show only discretionary activity)</span>
                </span>
              </label>
            </div>

            <button onClick={clearFilters} className="btn-ghost">
              Clear all filters
            </button>
          </div>
        )}
      </div>

      {/* Bulk Category Update Bar */}
      {!loading && paginatedTransactions.length > 0 && (
        <div className="card p-4 mb-4">
          {!isBulkCategoryMode ? (
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
              <div className="text-sm text-slate-400">
                {selectedTransactionIds.size > 0 ? (
                  <span>{selectedTransactionIds.size} transaction{selectedTransactionIds.size !== 1 ? 's' : ''} selected</span>
                ) : (
                  <span>Select transactions to update their category</span>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {selectedTransactionIds.size > 0 && (
                  <button onClick={handleDeselectAll} className="btn-ghost !py-1.5">
                    Deselect all
                  </button>
                )}
                <button
                  onClick={() => setIsBulkCategoryMode(true)}
                  disabled={selectedTransactionIds.size === 0}
                  className="btn-primary !py-1.5"
                >
                  Set category
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium text-slate-200">
                  Setting category for {selectedTransactionIds.size} transaction{selectedTransactionIds.size !== 1 ? 's' : ''}
                </div>
                <button onClick={handleCancelBulkMode} className="text-sm text-slate-400 hover:text-slate-200">
                  Cancel
                </button>
              </div>

              {isBulkAddingCategory ? (
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={bulkNewCategoryName}
                    onChange={(e) => setBulkNewCategoryName(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && handleAddBulkCustomCategory()}
                    placeholder="New category name"
                    className="input flex-1"
                    autoFocus
                  />
                  <button onClick={handleAddBulkCustomCategory} className="btn-primary">
                    Add
                  </button>
                  <button
                    onClick={() => { setIsBulkAddingCategory(false); setBulkNewCategoryName('') }}
                    className="btn-ghost"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <select
                    value={bulkCategory}
                    onChange={(e) => {
                      if (e.target.value === '__ADD_NEW__') {
                        setIsBulkAddingCategory(true)
                      } else {
                        setBulkCategory(e.target.value)
                      }
                    }}
                    className="input flex-1"
                  >
                    <option value="">Uncategorized</option>
                    {categories.map(cat => (
                      <option key={cat} value={cat}>
                        {cat}
                      </option>
                    ))}
                    <option value="__ADD_NEW__">+ Add New Category</option>
                  </select>
                  <button onClick={handleBulkUpdateCategory} disabled={isUpdatingBulk} className="btn-primary">
                    {isUpdatingBulk ? 'Updating…' : 'Apply'}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Transactions List */}
      <div className="card overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-slate-500">Loading transactions…</div>
        ) : paginatedTransactions.length === 0 ? (
          <div className="p-8 text-center text-slate-500">
            {allTransactions.length === 0
              ? 'No transactions found. Sync transactions first.'
              : 'No transactions match your filters. Try adjusting your filters.'}
          </div>
        ) : (
          <>
          {/* Mobile card list */}
          <div className="md:hidden">
            <div className="px-4 py-2 border-b border-white/[0.06] bg-white/[0.02]">
              <button onClick={handleSelectAll} className="text-xs font-medium text-accent hover:text-accent-bright uppercase">
                Select All ({filteredAndSortedTransactions.length})
              </button>
            </div>
            <div className="divide-y divide-white/[0.06]">
              {paginatedTransactions.map((transaction) => (
                <div key={transaction.id} className="p-4">
                  <div className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      checked={selectedTransactionIds.has(transaction.id)}
                      onChange={() => handleToggleTransaction(transaction.id)}
                      className="checkbox mt-1"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-2">
                        <div className="text-sm font-medium text-slate-100 break-words">
                          {transaction.merchant_name || transaction.description}
                        </div>
                        <div className={`text-sm font-semibold whitespace-nowrap tnum ${
                          transaction.transaction_type === 'credit' ? 'text-pos' : 'text-slate-200'
                        }`}>
                          {transaction.transaction_type === 'credit' ? '+' : '−'}
                          {formatCurrency(transaction.amount, transaction.currency)}
                        </div>
                      </div>
                      {transaction.merchant_name && (
                        <div className="text-xs text-slate-500 break-words">{transaction.description}</div>
                      )}
                      <div className="text-xs text-slate-500 mt-0.5">
                        {formatDate(transaction.transaction_date)} · {getAccountName(transaction.account_id)}
                        {transaction.is_commitment && <span className="ml-2 chip-warn">Bill</span>}
                        {transaction.is_recurring && <span className="ml-2 chip-info">Recurring</span>}
                        {transaction.is_financed && <span className="ml-2 chip-info">On finance</span>}
                      </div>
                      <div className="mt-2 flex items-center justify-between gap-2">
                        <div className="flex-1 min-w-0">{renderCategoryEditor(transaction)}</div>
                        <div className="flex gap-3 whitespace-nowrap">
                          <button
                            onClick={() => setRuleTx(transaction)}
                            className="text-xs text-slate-500 hover:text-accent transition-colors inline-flex items-center gap-1"
                            title="Create a categorization rule from this transaction"
                          >
                            <Wand2 className="w-3.5 h-3.5" /> Rule
                          </button>
                          <button
                            onClick={() => setRecurringTx(transaction)}
                            className="text-xs text-slate-500 hover:text-accent transition-colors inline-flex items-center gap-1"
                            title="Mark as a recurring commitment"
                          >
                            <Repeat className="w-3.5 h-3.5" /> Recurring
                          </button>
                          {transaction.transaction_type === 'debit' && (
                            <button
                              onClick={() => setFinanceTx(transaction)}
                              className="text-xs text-slate-500 hover:text-accent transition-colors inline-flex items-center gap-1"
                              title="Pay this off over time on a payment plan"
                            >
                              <CreditCard className="w-3.5 h-3.5" /> Finance
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Desktop table */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full">
              <thead className="bg-white/[0.02] border-b border-white/[0.06]">
                <tr>
                  <th className="px-4 py-3 text-left">
                    <button
                      onClick={handleSelectAll}
                      className="text-xs font-medium text-accent hover:text-accent-bright uppercase tracking-wider"
                      title={`Select all ${filteredAndSortedTransactions.length} filtered transactions`}
                    >
                      Select All ({filteredAndSortedTransactions.length})
                    </button>
                  </th>
                  <th
                    className="th cursor-pointer hover:bg-white/[0.04] select-none"
                    onClick={() => {
                      const newDirection = sortField === 'date' && sortDirection === 'asc' ? 'desc' : 'asc'
                      setSortField('date')
                      setSortDirection(newDirection)
                    }}
                  >
                    <div className="flex items-center gap-1">
                      Date
                      {sortField === 'date' && (
                        <span className="text-accent">{sortDirection === 'asc' ? '↑' : '↓'}</span>
                      )}
                    </div>
                  </th>
                  <th className="th">Description</th>
                  <th className="th">Account</th>
                  <th className="th">Category</th>
                  <th
                    className="th !text-right cursor-pointer hover:bg-white/[0.04] select-none"
                    onClick={() => {
                      const newDirection = sortField === 'amount' && sortDirection === 'asc' ? 'desc' : 'asc'
                      setSortField('amount')
                      setSortDirection(newDirection)
                    }}
                  >
                    <div className="flex items-center justify-end gap-1">
                      Amount
                      {sortField === 'amount' && (
                        <span className="text-accent">{sortDirection === 'asc' ? '↑' : '↓'}</span>
                      )}
                    </div>
                  </th>
                  <th className="th !text-right"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06]">
                {paginatedTransactions.map((transaction) => (
                  <tr key={transaction.id} className="hover:bg-white/[0.03] transition-colors">
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selectedTransactionIds.has(transaction.id)}
                        onChange={() => handleToggleTransaction(transaction.id)}
                        className="checkbox"
                      />
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-400 whitespace-nowrap tnum">
                      {formatDate(transaction.transaction_date)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-sm font-medium text-slate-100">
                        {transaction.merchant_name || transaction.description}
                      </div>
                      {transaction.merchant_name && (
                        <div className="text-xs text-slate-500">
                          {transaction.description}
                        </div>
                      )}
                      {transaction.is_commitment && <span className="chip-warn mt-1 mr-1">Bill</span>}
                      {transaction.is_recurring && <span className="chip-info mt-1 mr-1">Recurring</span>}
                      {transaction.is_financed && <span className="chip-info mt-1">On finance</span>}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-400">
                      {getAccountName(transaction.account_id)}
                    </td>
                    <td className="px-4 py-3">
                      {renderCategoryEditor(transaction)}
                    </td>
                    <td className={`px-4 py-3 text-sm font-semibold text-right whitespace-nowrap tnum ${
                      transaction.transaction_type === 'credit' ? 'text-pos' : 'text-slate-200'
                    }`}>
                      {transaction.transaction_type === 'credit' ? '+' : '−'}
                      {formatCurrency(transaction.amount, transaction.currency)}
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      <button
                        onClick={() => setRuleTx(transaction)}
                        className="text-xs text-slate-500 hover:text-accent transition-colors mr-3"
                        title="Create a categorization rule from this transaction"
                      >
                        + Rule
                      </button>
                      <button
                        onClick={() => setRecurringTx(transaction)}
                        className="text-xs text-slate-500 hover:text-accent transition-colors"
                        title="Mark as a recurring commitment"
                      >
                        ↻ Recurring
                      </button>
                      {transaction.transaction_type === 'debit' && (
                        <button
                          onClick={() => setFinanceTx(transaction)}
                          className="text-xs text-slate-500 hover:text-accent transition-colors ml-3"
                          title="Pay this off over time on a payment plan"
                        >
                          ⊞ Finance
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}

        {/* Pagination */}
        {!loading && allTransactions.length > 0 && totalPages > 0 && (() => {
          const startItem = startIndex + 1
          const endItem = Math.min(endIndex, totalFiltered)

          // Generate page numbers to display
          const getPageNumbers = () => {
            const pages = []
            const maxPagesToShow = 7

            if (totalPages <= maxPagesToShow) {
              // Show all pages
              for (let i = 1; i <= totalPages; i++) {
                pages.push(i)
              }
            } else {
              // Always show first page
              pages.push(1)

              if (page > 3) {
                pages.push('...')
              }

              // Show pages around current page
              const start = Math.max(2, page - 1)
              const end = Math.min(totalPages - 1, page + 1)

              for (let i = start; i <= end; i++) {
                pages.push(i)
              }

              if (page < totalPages - 2) {
                pages.push('...')
              }

              // Always show last page
              pages.push(totalPages)
            }

            return pages
          }

          const pageBtn = 'px-3 py-1 rounded-lg text-sm border border-white/10 text-slate-300 hover:bg-white/[0.06] disabled:opacity-40 disabled:cursor-not-allowed transition-colors'

          return (
            <div className="px-4 py-3 border-t border-white/[0.06]">
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 mb-3">
                <div className="text-sm text-slate-400">
                  Showing {startItem}-{endItem} of {totalFiltered} transaction{totalFiltered !== 1 ? 's' : ''}
                  {totalFiltered !== allTransactions.length && (
                    <span className="text-slate-600"> (filtered from {allTransactions.length} total)</span>
                  )}
                </div>
                <div className="text-sm text-slate-500">
                  Page {page} of {totalPages}
                </div>
              </div>

              <div className="flex items-center justify-center gap-1">
                <button onClick={() => setPage(1)} disabled={page === 1} className={`hidden sm:block ${pageBtn}`}>
                  First
                </button>
                <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className={pageBtn}>
                  Previous
                </button>

                <div className="hidden sm:flex items-center gap-1">
                  {getPageNumbers().map((pageNum, idx) => (
                    pageNum === '...' ? (
                      <span key={`ellipsis-${idx}`} className="px-2 py-1 text-slate-600">
                        ...
                      </span>
                    ) : (
                      <button
                        key={pageNum}
                        onClick={() => setPage(pageNum as number)}
                        className={
                          page === pageNum
                            ? 'px-3 py-1 rounded-lg text-sm bg-accent text-ink-950 font-medium'
                            : pageBtn
                        }
                      >
                        {pageNum}
                      </button>
                    )
                  ))}
                </div>

                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className={pageBtn}
                >
                  Next
                </button>
                <button
                  onClick={() => setPage(totalPages)}
                  disabled={page === totalPages}
                  className={`hidden sm:block ${pageBtn}`}
                >
                  Last
                </button>
              </div>
            </div>
          )
        })()}
      </div>

      {toast && (
        <div className="fixed bottom-24 md:bottom-6 right-4 sm:right-6 z-50 bg-accent text-ink-950 font-medium px-4 py-3 rounded-xl shadow-pop">
          {toast}
        </div>
      )}

      {recurringTx && (
        <MakeRecurringModal
          transaction={recurringTx}
          onClose={() => setRecurringTx(null)}
          onDone={(label) => {
            setRecurringTx(null)
            setToast(`"${label}" added to Plan`)
            setTimeout(() => setToast(''), 3500)
          }}
        />
      )}

      {financeTx && (
        <PayOnFinanceModal
          transaction={financeTx}
          onClose={() => setFinanceTx(null)}
          onDone={(label) => {
            setFinanceTx(null)
            setToast(`"${label}" moved to a payment plan`)
            setTimeout(() => setToast(''), 3500)
            loadAllTransactions()
          }}
        />
      )}

      {ruleTx && (
        <AddRuleModal
          initialPattern={(ruleTx.merchant_name || ruleTx.description || '').trim()}
          initialCategory={ruleTx.category ?? ''}
          categories={categories}
          onClose={() => setRuleTx(null)}
          onAdded={async (result) => {
            setRuleTx(null)
            // The modal already backfilled (if opted in) — just reflect the result.
            setToast(
              result?.applied
                ? `Rule added · recategorized ${result.changed} transaction${result.changed !== 1 ? 's' : ''}`
                : 'Rule added',
            )
            setTimeout(() => setToast(''), 3500)
            await loadAllTransactions()
          }}
        />
      )}
    </div>
  )
}

function MakeRecurringModal({
  transaction,
  onClose,
  onDone,
}: {
  transaction: Transaction
  onClose: () => void
  onDone: (label: string) => void
}) {
  const [cadence, setCadence] = useState('monthly')
  const [saving, setSaving] = useState(false)
  const label = transaction.merchant_name || transaction.description || 'this transaction'

  const save = async () => {
    setSaving(true)
    try {
      await analyticsAPI.markTransactionRecurring(transaction.id, cadence)
      onDone(label)
    } catch (e) {
      console.error('Failed to mark recurring', e)
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel !max-w-sm" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-1">Mark as recurring</h3>
        <p className="text-sm text-slate-400 mb-4">
          Add <span className="font-medium text-slate-200">{label}</span> ({transaction.transaction_type === 'credit' ? 'income' : 'expense'}) as a
          confirmed commitment so it feeds your safe-to-spend and forecast.
        </p>
        <label className="label">How often?</label>
        <select value={cadence} onChange={(e) => setCadence(e.target.value)} className="input mb-5">
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
          <option value="every_n_months">Every few months</option>
          <option value="yearly">Yearly</option>
        </select>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={save} disabled={saving} className="btn-primary">
            {saving ? 'Adding…' : 'Add to plan'}
          </button>
        </div>
      </div>
    </div>
  )
}

function PayOnFinanceModal({
  transaction,
  onClose,
  onDone,
}: {
  transaction: Transaction
  onClose: () => void
  onDone: (label: string) => void
}) {
  const label = transaction.merchant_name || transaction.description || 'this purchase'
  const [months, setMonths] = useState(12)
  // Default the per-month amount to an even split of the purchase, rounded to pennies.
  const [monthly, setMonthly] = useState(() => (transaction.amount / 12).toFixed(2))
  // First payment defaults to ~a month out.
  const [startDate, setStartDate] = useState(() => {
    const d = new Date()
    d.setMonth(d.getMonth() + 1)
    return d.toISOString().slice(0, 10)
  })
  const [saving, setSaving] = useState(false)

  const setMonthsAndSplit = (m: number) => {
    setMonths(m)
    setMonthly((transaction.amount / Math.max(m, 1)).toFixed(2))
  }

  const total = (Number(monthly) || 0) * months
  const gbp = (n: number) =>
    new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(n)

  const save = async () => {
    if (!months || !monthly || Number(monthly) <= 0 || !startDate) return
    setSaving(true)
    try {
      await analyticsAPI.payOnFinance({
        transaction_id: transaction.id,
        months,
        monthly_amount: Number(monthly),
        start_date: startDate,
      })
      onDone(label)
    } catch (e) {
      console.error('Failed to move to a payment plan', e)
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel !max-w-sm" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-1">Pay on finance</h3>
        <p className="text-sm text-slate-400 mb-4">
          Split <span className="font-medium text-slate-200">{label}</span> ({gbp(transaction.amount)})
          into a payment plan. It leaves your Spending totals and the installments show in your forecast.
        </p>
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div>
            <label className="label">Number of months</label>
            <input
              type="number" min={1} max={120} value={months}
              onChange={(e) => setMonthsAndSplit(Number(e.target.value))}
              className="input"
            />
          </div>
          <div>
            <label className="label">Amount per month (£)</label>
            <input
              type="number" min={0} step="0.01" value={monthly}
              onChange={(e) => setMonthly(e.target.value)}
              className="input"
            />
          </div>
          <div className="col-span-2">
            <label className="label">First payment</label>
            <input
              type="date" value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="input"
            />
          </div>
        </div>
        <p className="text-xs text-slate-500 mb-4">
          {gbp(Number(monthly) || 0)} × {months} = {gbp(total)} total
          {Math.abs(total - transaction.amount) > 0.5 && (
            <span className="text-slate-400"> · {gbp(total - transaction.amount)} vs the purchase</span>
          )}
        </p>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={save} disabled={saving} className="btn-primary">
            {saving ? 'Saving…' : 'Move to plan'}
          </button>
        </div>
      </div>
    </div>
  )
}

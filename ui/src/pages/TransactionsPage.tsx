import React, { useEffect, useState } from 'react'
import { bankingAPI } from '../services/api'

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
  transaction_date: string
}

interface Account {
  id: string
  display_name: string
  provider_name: string
}

export default function TransactionsPage() {
  const [allTransactions, setAllTransactions] = useState<Transaction[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(50)
  const [editingTransactionId, setEditingTransactionId] = useState<string | null>(null)
  const [editingCategory, setEditingCategory] = useState<string>('')
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

  useEffect(() => {
    loadAccounts()
    loadAllTransactions()
  }, [selectedAccount])

  // Reset to page 1 when filters or sort changes
  useEffect(() => {
    setPage(1)
  }, [searchTerm, selectedCategories, startDate, endDate, minAmount, maxAmount, selectedMerchant, selectedType, hideInternalTransfers, sortField, sortDirection])

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

      console.log(`Loaded ${transactions.length} transactions, ${uniqueTransactions.length} unique`)
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
    console.log(`Processing ${allTransactions.length} total transactions`)
    console.log(`Active filters:`, { searchTerm, selectedCategories, selectedAccount, startDate, endDate, minAmount, maxAmount, selectedMerchant, selectedType, hideInternalTransfers })
    console.log(`Active sort:`, { sortField, sortDirection })

    // Debug: Check sample transaction amounts and types
    if (allTransactions.length > 0) {
      console.log('Sample transactions:', allTransactions.slice(0, 5).map(tx => ({
        amount: tx.amount,
        type: tx.transaction_type,
        desc: tx.description
      })))
    }

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

      console.log(`Detected ${internalTransferIds.size} internal transfer transactions (within 2-day window)`)
      transactionsToFilter = allTransactions.filter(tx => !internalTransferIds.has(tx.id))
    }

    // First, filter ALL transactions (excluding internal transfers if enabled)
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

    console.log(`After filtering: ${filtered.length} transactions`)

    // Then, sort if a sort field is selected
    if (!sortField) {
      console.log('No sort field selected, returning filtered results')
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

    console.log(`After sorting by ${sortField} (${sortDirection}): ${sorted.length} transactions`)
    if (sorted.length > 0) {
      console.log('First 5 after sort:', sorted.slice(0, 5).map(t => ({
        desc: t.description,
        amount: t.amount,
        absAmount: Math.abs(t.amount),
        date: t.transaction_date
      })))
    }

    return sorted
  }, [allTransactions, searchTerm, selectedCategories, selectedType, startDate, endDate, minAmount, maxAmount, selectedMerchant, hideInternalTransfers, sortField, sortDirection])

  // Get unique categories from all loaded transactions + custom ones
  const categories = Array.from(new Set([
    ...allTransactions.map(tx => tx.category).filter(Boolean),
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

  // Check if sorting is active (always show pagination now since everything is client-side)
  const isSorted = sortField !== null

  // Calculate totals
  const totalSpent = filteredAndSortedTransactions
    .filter(tx => tx.transaction_type === 'debit')
    .reduce((sum, tx) => sum + tx.amount, 0)

  const totalIncome = filteredAndSortedTransactions
    .filter(tx => tx.transaction_type === 'credit')
    .reduce((sum, tx) => sum + tx.amount, 0)

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Transactions</h1>
        <div className="flex items-center gap-4">
          <div className="text-sm text-gray-600">
            {allTransactions.length} total transactions
          </div>
          <button
            onClick={handleDownloadCSV}
            disabled={filteredAndSortedTransactions.length === 0}
            className="px-4 py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            title={`Download ${filteredAndSortedTransactions.length} filtered transactions as CSV`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Download CSV
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid md:grid-cols-3 gap-4 mb-6">
        <div className="p-4 bg-red-50 rounded-lg border border-red-200">
          <div className="text-sm text-red-600 mb-1">Total Spent</div>
          <div className="text-2xl font-bold text-red-700">
            {formatCurrency(totalSpent)}
          </div>
        </div>
        <div className="p-4 bg-green-50 rounded-lg border border-green-200">
          <div className="text-sm text-green-600 mb-1">Total Income</div>
          <div className="text-2xl font-bold text-green-700">
            {formatCurrency(totalIncome)}
          </div>
        </div>
        <div className="p-4 bg-blue-50 rounded-lg border border-blue-200">
          <div className="text-sm text-blue-600 mb-1">Net</div>
          <div className={`text-2xl font-bold ${totalIncome - totalSpent >= 0 ? 'text-green-700' : 'text-red-700'}`}>
            {formatCurrency(totalIncome - totalSpent)}
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white p-4 rounded-lg shadow-sm mb-6">
        <div className="grid md:grid-cols-3 gap-4 mb-4">
          {/* Search */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Search
            </label>
            <input
              type="text"
              placeholder="Search description or merchant..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {/* Account Filter */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Account
            </label>
            <select
              value={selectedAccount}
              onChange={(e) => setSelectedAccount(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="">All Accounts</option>
              {accounts.map(account => (
                <option key={account.id} value={account.id}>
                  {account.display_name}
                </option>
              ))}
            </select>
          </div>

          {/* Category Filter */}
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
              {['Uncategorized', ...categories].map(category => {
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

        {/* Date Range Filter */}
        <div className="grid md:grid-cols-3 gap-4">
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

          <div className="flex items-end">
            <button
              onClick={() => {
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
              }}
              className="w-full px-4 py-2 text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
            >
              Clear Filters
            </button>
          </div>
        </div>

        {/* Amount Range and Merchant Filter */}
        <div className="grid md:grid-cols-4 gap-4 mt-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Min Amount
            </label>
            <input
              type="number"
              step="0.01"
              placeholder="0.00"
              value={minAmount}
              onChange={(e) => setMinAmount(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Max Amount
            </label>
            <input
              type="number"
              step="0.01"
              placeholder="999999.99"
              value={maxAmount}
              onChange={(e) => setMaxAmount(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Merchant
            </label>
            <select
              value={selectedMerchant}
              onChange={(e) => setSelectedMerchant(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="">All Merchants</option>
              {merchants.map(merchant => (
                <option key={merchant} value={merchant}>
                  {merchant}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Transaction Type
            </label>
            <select
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="">All Transactions</option>
              <option value="debit">Expenses Only</option>
              <option value="credit">Income Only</option>
            </select>
          </div>
        </div>

        {/* Internal Transfers Toggle */}
        <div className="mt-4 pt-4 border-t border-gray-200">
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
      </div>

      {/* Bulk Category Update Bar */}
      {!loading && paginatedTransactions.length > 0 && (
        <div className="bg-white rounded-lg shadow-sm p-4 mb-4">
          {!isBulkCategoryMode ? (
            <div className="flex items-center justify-between">
              <div className="text-sm text-gray-600">
                {selectedTransactionIds.size > 0 ? (
                  <span>{selectedTransactionIds.size} transaction{selectedTransactionIds.size !== 1 ? 's' : ''} selected</span>
                ) : (
                  <span>Select transactions to update their category</span>
                )}
              </div>
              <div className="flex gap-2">
                {selectedTransactionIds.size > 0 && (
                  <button
                    onClick={handleDeselectAll}
                    className="px-3 py-1.5 text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
                  >
                    Deselect All
                  </button>
                )}
                <button
                  onClick={() => setIsBulkCategoryMode(true)}
                  disabled={selectedTransactionIds.size === 0}
                  className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  Set Category
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium text-gray-700">
                  Setting category for {selectedTransactionIds.size} transaction{selectedTransactionIds.size !== 1 ? 's' : ''}
                </div>
                <button
                  onClick={handleCancelBulkMode}
                  className="text-sm text-gray-600 hover:text-gray-800"
                >
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
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    autoFocus
                  />
                  <button
                    onClick={handleAddBulkCustomCategory}
                    className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700"
                  >
                    Add
                  </button>
                  <button
                    onClick={() => { setIsBulkAddingCategory(false); setBulkNewCategoryName('') }}
                    className="px-4 py-2 bg-gray-300 text-gray-700 rounded-lg hover:bg-gray-400"
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
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  >
                    <option value="">Uncategorized</option>
                    {categories.map(cat => (
                      <option key={cat} value={cat}>
                        {cat}
                      </option>
                    ))}
                    <option value="__ADD_NEW__" className="font-semibold text-blue-600">
                      + Add New Category
                    </option>
                  </select>
                  <button
                    onClick={handleBulkUpdateCategory}
                    disabled={isUpdatingBulk}
                    className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isUpdatingBulk ? 'Updating...' : 'Apply'}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Transactions List */}
      <div className="bg-white rounded-lg shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-gray-500">Loading transactions...</div>
        ) : paginatedTransactions.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            {allTransactions.length === 0
              ? 'No transactions found. Sync transactions first.'
              : 'No transactions match your filters. Try adjusting your filters.'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-4 py-3 text-left">
                    <button
                      onClick={handleSelectAll}
                      className="text-xs font-medium text-blue-600 hover:text-blue-800 uppercase"
                      title={`Select all ${filteredAndSortedTransactions.length} filtered transactions`}
                    >
                      Select All ({filteredAndSortedTransactions.length})
                    </button>
                  </th>
                  <th
                    className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase cursor-pointer hover:bg-gray-100 select-none"
                    onClick={() => {
                      console.log('Date clicked. Current:', { sortField, sortDirection })
                      const newDirection = sortField === 'date' && sortDirection === 'asc' ? 'desc' : 'asc'
                      console.log('Setting direction to:', newDirection)
                      setSortField('date')
                      setSortDirection(newDirection)
                    }}
                  >
                    <div className="flex items-center gap-1">
                      Date
                      {sortField === 'date' && (
                        <span className="text-blue-600">
                          {sortDirection === 'asc' ? '↑' : '↓'}
                        </span>
                      )}
                    </div>
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Account</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Category</th>
                  <th
                    className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase cursor-pointer hover:bg-gray-100 select-none"
                    onClick={() => {
                      console.log('Amount clicked. Current:', { sortField, sortDirection })
                      const newDirection = sortField === 'amount' && sortDirection === 'asc' ? 'desc' : 'asc'
                      console.log('Setting direction to:', newDirection)
                      setSortField('amount')
                      setSortDirection(newDirection)
                    }}
                  >
                    <div className="flex items-center justify-end gap-1">
                      Amount
                      {sortField === 'amount' && (
                        <span className="text-blue-600">
                          {sortDirection === 'asc' ? '↑' : '↓'}
                        </span>
                      )}
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {paginatedTransactions.map((transaction) => (
                  <tr key={transaction.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selectedTransactionIds.has(transaction.id)}
                        onChange={() => handleToggleTransaction(transaction.id)}
                        className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                      />
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900 whitespace-nowrap">
                      {formatDate(transaction.transaction_date)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-sm font-medium text-gray-900">
                        {transaction.merchant_name || transaction.description}
                      </div>
                      {transaction.merchant_name && (
                        <div className="text-xs text-gray-500">
                          {transaction.description}
                        </div>
                      )}
                      {transaction.is_recurring && (
                        <span className="inline-block mt-1 px-2 py-0.5 text-xs bg-purple-100 text-purple-800 rounded">
                          Recurring
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {getAccountName(transaction.account_id)}
                    </td>
                    <td className="px-4 py-3">
                      {editingTransactionId === transaction.id ? (
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
                                  className="w-full px-2 py-1 text-xs border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                                  autoFocus
                                />
                                <button
                                  onClick={handleAddCustomCategory}
                                  className="px-2 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700"
                                >
                                  Add
                                </button>
                                <button
                                  onClick={() => { setIsAddingCategory(false); setNewCategoryName('') }}
                                  className="px-2 py-1 text-xs bg-gray-300 text-gray-700 rounded hover:bg-gray-400"
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
                                className="w-full px-2 py-1 text-xs border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                                autoFocus
                              >
                                <option value="">Uncategorized</option>
                                {categories.map(cat => (
                                  <option key={cat} value={cat}>
                                    {cat}
                                  </option>
                                ))}
                                <option value="__ADD_NEW__" className="font-semibold text-blue-600">
                                  + Add New Category
                                </option>
                              </select>
                            )}
                          </div>
                          {!isAddingCategory && (
                            <>
                              <button
                                onClick={() => handleSaveCategory(transaction.id)}
                                className="px-2 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
                              >
                                Save
                              </button>
                              <button
                                onClick={handleCancelEdit}
                                className="px-2 py-1 text-xs bg-gray-300 text-gray-700 rounded hover:bg-gray-400"
                              >
                                Cancel
                              </button>
                            </>
                          )}
                        </div>
                      ) : (
                        <div
                          onClick={() => handleEditCategory(transaction)}
                          className="cursor-pointer group"
                        >
                          {transaction.category ? (
                            <span className="inline-block px-2 py-1 text-xs bg-gray-100 text-gray-700 rounded group-hover:bg-blue-100 group-hover:text-blue-700 transition-colors">
                              {transaction.category}
                            </span>
                          ) : (
                            <span className="text-xs text-gray-400 group-hover:text-blue-600 transition-colors">
                              Click to categorize
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className={`px-4 py-3 text-sm font-semibold text-right whitespace-nowrap ${
                      transaction.transaction_type === 'credit' ? 'text-green-600' : 'text-red-600'
                    }`}>
                      {transaction.transaction_type === 'credit' ? '+' : '-'}
                      {formatCurrency(transaction.amount, transaction.currency)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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

          return (
            <div className="px-4 py-3 border-t border-gray-200">
              <div className="flex items-center justify-between mb-3">
                <div className="text-sm text-gray-700">
                  Showing {startItem}-{endItem} of {totalFiltered} transaction{totalFiltered !== 1 ? 's' : ''}
                  {totalFiltered !== allTransactions.length && (
                    <span className="text-gray-500"> (filtered from {allTransactions.length} total)</span>
                  )}
                </div>
                <div className="text-sm text-gray-600">
                  Page {page} of {totalPages}
                </div>
              </div>

              <div className="flex items-center justify-center gap-1">
                <button
                  onClick={() => setPage(1)}
                  disabled={page === 1}
                  className="px-3 py-1 border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                >
                  First
                </button>
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-3 py-1 border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                >
                  Previous
                </button>

                {getPageNumbers().map((pageNum, idx) => (
                  pageNum === '...' ? (
                    <span key={`ellipsis-${idx}`} className="px-2 py-1 text-gray-400">
                      ...
                    </span>
                  ) : (
                    <button
                      key={pageNum}
                      onClick={() => setPage(pageNum as number)}
                      className={`px-3 py-1 border rounded text-sm ${
                        page === pageNum
                          ? 'bg-blue-600 text-white border-blue-600'
                          : 'border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      {pageNum}
                    </button>
                  )
                ))}

                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="px-3 py-1 border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                >
                  Next
                </button>
                <button
                  onClick={() => setPage(totalPages)}
                  disabled={page === totalPages}
                  className="px-3 py-1 border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                >
                  Last
                </button>
              </div>
            </div>
          )
        })()}
      </div>
    </div>
  )
}

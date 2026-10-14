import { useCallback, useEffect, useState } from 'react'
import { analyticsAPI, type CardStatements } from '../../services/api'
import StatementView, { type StatementStatus } from './StatementView'

/** Loads a card's statements for the Statement block (ux T-10-0 A.2). A
 *  404 (a foreign or unknown card) is reported up so the modal disables Save
 *  (C-21). Until the account is saved as a credit card nothing is fetched. */
export default function StatementBlock({
  accountId, savedAsCredit, currentBalance, providerName, onNotFound,
}: {
  accountId: string
  savedAsCredit: boolean
  currentBalance: string
  providerName: string
  onNotFound: () => void
}) {
  const [status, setStatus] = useState<StatementStatus>(savedAsCredit ? 'loading' : 'unsaved')
  const [data, setData] = useState<CardStatements | null>(null)

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const res = await analyticsAPI.getStatements(accountId)
      setData(res.data)
      setStatus('ready')
    } catch (e) {
      const notFound = (e as { response?: { status?: number } })?.response?.status === 404
      setStatus(notFound ? 'notfound' : 'error')
      if (notFound) onNotFound()
    }
  }, [accountId, onNotFound])

  useEffect(() => {
    if (savedAsCredit) load()
  }, [savedAsCredit, load])

  return (
    <StatementView
      status={savedAsCredit ? status : 'unsaved'}
      data={data}
      currentBalance={currentBalance}
      providerName={providerName}
      onRetry={load}
    />
  )
}

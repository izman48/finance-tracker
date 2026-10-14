import { useCallback, useEffect, useState } from 'react'
import { analyticsAPI, type CardStatement, type CardStatements } from '../../services/api'
import { useConfirm } from '../ui/ConfirmDialog'
import { useToast } from '../ui/Toast'
import {
  editFormFor,
  manualFor,
  pickStatement,
  removeStatement,
  saveStatement,
  type StatementErrors,
  type StatementForm as Form,
} from '../../lib/statements'
import StatementForm from './StatementForm'
import StatementView, { type StatementStatus } from './StatementView'

/** The Statement block in card settings (ux T-10-0 A.2-A.4): loads the
 *  card's statements, and adds, edits, deletes and picks between manual and
 *  provider statements. The rules and copy live in lib/statements (tested);
 *  this wires them to the API, the confirm dialog, toasts and focus. A 404
 *  is reported up so the modal disables Save (C-21). */
type Editing = { mode: 'add' | 'edit'; statementId: string | null; replacingProvider: boolean }

const EMPTY: Form = { statement_balance: '', statement_date: '', due_date: '', minimum_due: '' }
const localToday = () => new Date().toLocaleDateString('en-CA') // YYYY-MM-DD, the user's own day
const focusLater = (id: string) => window.setTimeout(() => document.getElementById(id)?.focus(), 0)

export default function StatementBlock({
  accountId, savedAsCredit, currentBalance, providerName, onNotFound,
}: {
  accountId: string
  savedAsCredit: boolean
  currentBalance: string
  providerName: string
  onNotFound: () => void
}) {
  const confirm = useConfirm()
  const toast = useToast()
  const [status, setStatus] = useState<StatementStatus>(savedAsCredit ? 'loading' : 'unsaved')
  const [data, setData] = useState<CardStatements | null>(null)
  const [editing, setEditing] = useState<Editing | null>(null)
  const [form, setForm] = useState<Form>(EMPTY)
  const [errors, setErrors] = useState<StatementErrors>({})
  const [saveError, setSaveError] = useState<'duplicate' | 'error' | null>(null)
  const [busy, setBusy] = useState<'saving' | 'deleting' | 'using' | null>(null)
  const [choice, setChoice] = useState<string | undefined>()
  const [useError, setUseError] = useState(false)

  const load = useCallback(async () => {
    setStatus((s) => (s === 'ready' ? s : 'loading'))
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

  const open = (next: Editing, values: Form) => {
    setEditing(next)
    setForm(values)
    setErrors({})
    setSaveError(null)
    focusLater('statement-balance')
  }
  const openEdit = (statement: CardStatement) => {
    const { form: values, replacingProvider } = editFormFor(statement)
    open({ mode: 'edit', statementId: statement.id, replacingProvider }, values)
  }
  const close = () => setEditing(null)

  const submit = async () => {
    if (!editing) return
    setBusy('saving')
    const outcome = await saveStatement(analyticsAPI, accountId, form, editing.statementId, localToday())
    setBusy(null)
    if (outcome.kind === 'invalid') {
      setErrors(outcome.errors)
      focusLater('statement-errors')
      return
    }
    setErrors({})
    if (outcome.kind !== 'saved') {
      setSaveError(outcome.kind)
      return
    }
    close()
    await load()
    toast('Statement saved.')
    focusLater('statement-edit')
  }

  const remove = async () => {
    if (!editing?.statementId || !data) return
    setBusy('deleting')
    const outcome = await removeStatement(analyticsAPI, confirm, accountId, editing.statementId, {
      otherStatements: data.statements.length > 1,
      currentBalance,
    })
    setBusy(null)
    if (outcome === 'cancelled') return
    if (outcome === 'error') {
      setSaveError('error')
      return
    }
    close()
    await load()
    toast('Statement deleted.')
  }

  const use = async () => {
    const current = data?.current
    const mine = current && data ? manualFor(data.statements, current.statement_date) : undefined
    if (!choice || !mine || choice === mine.id) return
    setBusy('using')
    setUseError(false)
    const outcome = await pickStatement(analyticsAPI, confirm, accountId, choice, mine, providerName)
    setBusy(null)
    if (outcome === 'error') setUseError(true)
    if (outcome !== 'used') return
    setChoice(undefined)
    await load()
    toast(`Now using the statement from ${providerName}.`)
  }

  const current = data?.current ?? null
  const duplicate = data ? manualFor(data.statements, form.statement_date) : undefined
  const formNode = editing && (
    <StatementForm
      mode={editing.mode}
      form={form}
      errors={errors}
      saveError={saveError}
      saving={busy === 'saving'}
      deleting={busy === 'deleting'}
      providerName={providerName}
      replacingProvider={editing.replacingProvider}
      onChange={(patch) => setForm((f) => ({ ...f, ...patch }))}
      onSubmit={submit}
      onCancel={close}
      onDelete={editing.mode === 'edit' && !editing.replacingProvider ? remove : undefined}
      onEditDuplicate={duplicate ? () => openEdit(duplicate) : undefined}
    />
  )

  return (
    <StatementView
      status={savedAsCredit ? status : 'unsaved'}
      data={data}
      currentBalance={currentBalance}
      providerName={providerName}
      choice={choice}
      busy={busy !== null}
      useError={useError}
      form={formNode || undefined}
      onRetry={load}
      onAdd={() => open({ mode: 'add', statementId: null, replacingProvider: false }, EMPTY)}
      onEdit={() => {
        const row = current && data?.statements.find((s) => s.id === current.statement_id)
        if (row) openEdit(row)
      }}
      onChoose={setChoice}
      onUse={use}
    />
  )
}

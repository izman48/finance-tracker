import type { ReactNode } from 'react'
import { dateLong, money } from '../../lib/format'
import { statementSentence } from '../../lib/statements'
import type { CardStatement, CardStatements } from '../../services/api'

/** The Statement block inside card settings (ux T-10-0 A.2, A.4). Purely
 *  presentational: every figure is the API's, formatted; every name is
 *  rendered as text. The container (StatementBlock) owns loading and writes. */
export type StatementStatus = 'loading' | 'error' | 'notfound' | 'unsaved' | 'ready'

export interface StatementViewProps {
  status: StatementStatus
  data: CardStatements | null
  /** Money owed now (the API's credit_owed), for the empty and missing states. */
  currentBalance: string
  /** No repayment set up (T-10-12): the forecast plans nothing for it. */
  notInForecast?: boolean
  providerName: string
  /** The radio picked in the conflict pair (defaults to the one in use). */
  choice?: string
  busy?: boolean
  onRetry: () => void
  /** Write actions; a button shows only when its action is given. */
  onAdd?: () => void
  onEdit?: () => void
  onChoose?: (statementId: string) => void
  onUse?: () => void
  /** The add/edit form, shown in place of the rows while open. */
  form?: ReactNode
  /** "Use this statement" failed. */
  useError?: boolean
}

const pounds = (amount: string | number) => money(Number(amount))
/** Only a card that owes money has a balance to plan (a card in credit
 *  must never read "full current balance of -£x"). */
const owes = (balance: string) => Number(balance) > 0

export default function StatementView(props: StatementViewProps) {
  const { status, data } = props
  return (
    <section aria-labelledby="statement-heading" aria-busy={status === 'loading' ? true : undefined} className="mb-4">
      <div className="flex items-center gap-2 mb-2">
        <h4 id="statement-heading" className="text-sm font-semibold text-slate-100">Statement</h4>
        {status === 'ready' && data?.current && (
          <span className="chip">{data.current.source === 'provider' ? `From ${props.providerName}` : 'Entered by you'}</span>
        )}
      </div>
      <Body {...props} data={data} />
    </section>
  )
}

function Body(props: StatementViewProps) {
  const { status, data } = props
  if (status === 'ready' && props.form) return <>{props.form}</>
  if (status === 'unsaved') {
    return <p className="text-sm text-slate-400">Save this account as a credit card first, then you can add a statement.</p>
  }
  if (status === 'loading') return <p role="status" className="text-sm text-slate-400">Loading statement…</p>
  if (status === 'notfound') {
    return <div role="alert" className="banner-err">We could not find this card. Close this window and reload the page.</div>
  }
  if (status === 'error' || !data) {
    return (
      <div role="alert" className="banner-err">
        We could not load this card's statement. Your repayment settings below are unchanged. Try again, or close
        this window and reopen it.
        <button type="button" onClick={props.onRetry} className="btn-ghost mt-2">Try again</button>
      </div>
    )
  }
  if (!data.current) {
    return (
      <div>
        <p className="text-sm text-slate-300 mb-2">
          No statement entered yet.{' '}
          {props.notInForecast
            ? ''
            : owes(props.currentBalance)
            ? `Until you add one, nilu plans to pay your full current balance of ${pounds(props.currentBalance)} on the card's next payment date.`
            : 'nilu has no balance to plan for this card yet.'}
        </p>
        {props.onAdd && (
          <button type="button" id="statement-add" onClick={props.onAdd} className="btn-ghost">Add statement</button>
        )}
      </div>
    )
  }
  const current = data.current
  const sentence = statementSentence(data)
  return (
    <div className="space-y-3">
      {data.missing_statement && (
        <div className="banner-info">
          Your statement due {dateLong(current.due_date)} has passed. Add your new statement so nilu plans the right
          bill.
          {owes(props.currentBalance) && ` Until then it plans your full current balance of ${pounds(props.currentBalance)}.`}
          {props.onAdd && (
            <button type="button" id="statement-add" onClick={props.onAdd} className="btn-primary mt-2">Add new statement</button>
          )}
        </div>
      )}
      {data.conflict && <Conflict {...props} data={data} />}
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
        <Row term="Statement balance" value={pounds(current.statement_balance)} />
        <Row term="Statement date" value={dateLong(current.statement_date)} />
        <Row
          term="Due date"
          value={dateLong(current.due_date)}
          chip={data.missing_statement ? <span className="chip">Past due date</span> : null}
        />
        {current.minimum_due !== null && <Row term="Minimum payment" value={pounds(current.minimum_due)} />}
        <Row
          term="Still to pay"
          value={pounds(current.amount_still_due)}
          chip={current.paid ? <span className="chip-pos">Paid</span> : null}
        />
        <Row term="Spent since the statement" value={pounds(current.unbilled)} />
      </dl>
      {props.onEdit && (
        <button type="button" id="statement-edit" onClick={props.onEdit} className="btn-ghost">Edit statement</button>
      )}
      {sentence && <p className="text-sm text-slate-300">{sentence}</p>}
    </div>
  )
}

function Row({ term, value, chip }: { term: string; value: string; chip?: ReactNode }) {
  return (
    <>
      <dt className="text-slate-400">{term}</dt>
      <dd className="text-slate-100 tnum text-right">
        {value} {chip}
      </dd>
    </>
  )
}

/** Manual and provider figures for the current period differ (A.4). Manual is
 *  in use; picking the provider's asks first (StatementBlock). */
function Conflict(props: StatementViewProps & { data: CardStatements }) {
  const period = props.data.current!.statement_date
  const pair = props.data.statements.filter((s) => s.statement_date === period)
  const inUse = props.data.current!.statement_id
  const choice = props.choice ?? inUse
  return (
    <div className="space-y-2">
      <div className="banner-info">
        Your figures and {props.providerName}'s figures for this statement are different.
        {props.onUse && ' Pick the one that matches your paper or app statement.'}
      </div>
      {!props.onUse ? (
        <ul className="space-y-1 text-sm">
          {pair.map((s) => (
            <li key={s.id}>
              <span className="text-slate-100">{s.source === 'provider' ? `From ${props.providerName}` : 'Entered by you'}</span>{' '}
              <span className="text-slate-400 tnum">{describe(s)}</span>
            </li>
          ))}
        </ul>
      ) : (
      <fieldset className="space-y-2">
        <legend className="label">Which statement is right?</legend>
        {pair.map((s) => (
          <label key={s.id} className="flex items-start gap-2 rounded-lg border border-white/10 p-3 min-h-[44px] focus-within:outline focus-within:outline-2 focus-within:outline-accent">
            <input
              type="radio"
              name="statement-choice"
              value={s.id}
              checked={choice === s.id}
              onChange={() => props.onChoose?.(s.id)}
            />
            <span className="text-sm">
              <span className="block text-slate-100">
                {s.source === 'provider' ? `From ${props.providerName}` : 'Entered by you'}{' '}
                <span className="chip-warn">Different</span>
              </span>
              <span className="block text-slate-400 tnum">{describe(s)}</span>
            </span>
          </label>
        ))}
      </fieldset>
      )}
      {props.onUse && (
        <button type="button" id="statement-use" onClick={props.onUse} disabled={props.busy || choice === inUse} className="btn-primary">
          Use this statement
        </button>
      )}
      {props.useError && (
        <div role="alert" className="banner-err">
          We could not change which statement is used. Nothing was changed. Try again.
        </div>
      )}
    </div>
  )
}

function describe(s: CardStatement): string {
  return `${pounds(s.statement_balance)} · statement ${dateLong(s.statement_date)} · due ${dateLong(s.due_date)}`
}

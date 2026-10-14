import { warningText, type RepaymentWarning } from '../../lib/repaymentWarnings'

/** The API's repayment warnings for one control (ux T-10-0 A.6). The live
 *  region is always rendered so assistive tech hears warnings that appear
 *  after Save; each line is text with a visually hidden "Warning:" prefix. */
export default function RepaymentWarnings({
  warnings, codes, providerName,
}: {
  warnings: RepaymentWarning[]
  codes: RepaymentWarning['code'][]
  providerName: string
}) {
  const mine = warnings.filter((w) => codes.includes(w.code))
  return (
    <div aria-live="polite" className="space-y-1">
      {mine.map((w) => (
        <div key={w.code} className="flex gap-2 text-xs text-warn mt-1">
          <span aria-hidden="true">⚠</span>
          <span>
            <span className="sr-only">Warning: </span>
            {warningText(w, providerName)}
          </span>
        </div>
      ))}
    </div>
  )
}

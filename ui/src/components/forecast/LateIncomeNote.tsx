import { Clock } from 'lucide-react'
import { lateIncomeNote } from '../../lib/late'

/** Between the forecast headline and the chart (ux spec 3, L2). It never changes the line. */
export default function LateIncomeNote({ items }: { items: { amount: number | string }[] }) {
  const note = lateIncomeNote(items)
  if (!note) return null
  return (
    <p className="text-sm text-warn flex items-start gap-1.5 mb-2">
      <Clock className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
      <span>{note}</span>
    </p>
  )
}

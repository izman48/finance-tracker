// One place for the "how is this number calculated?" tooltip copy, so stats
// that appear on several pages (cash / credit / net worth) stay consistent.
// Keep these honest: they must describe what analytics_service.py actually
// computes, not what marketing wishes it computed.

export const EXPLAIN = {
  safeToSpend:
    'Your available cash minus everything already committed before your next payday: confirmed recurring bills plus scheduled card repayments. Your overdraft is never counted. If commitments exceed cash this shows £0 — the forecast below shows how deep the dip goes.',
  availableCash:
    'The combined current balance of every account marked as “Spending”. Savings and credit cards are tracked separately.',
  committedSoon:
    'Bills you’ve confirmed as recurring that fall due before your next payday, plus any scheduled credit-card repayments in the same window.',
  savable:
    'What should survive the next 30 days: available cash, plus income expected in that window, minus bills and card repayments due in it. Clamped at £0.',
  overdraftCushion:
    'The total arranged overdraft across your spending accounts. Shown as a safety net only — it’s never added to “safe to spend”.',
  creditOwed:
    'The combined balance across your credit cards. The repayments listed come from each card’s repayment schedule (full balance or installments — configurable per card).',
  netWorth:
    'Available cash + savings + other assets you’ve added manually, minus what you owe on credit.',
  spentSincePayday:
    'Everything spent since your last payday: money out of spending accounts plus new purchases on credit cards. Internal transfers and card repayments are excluded, so paying off a card never double-counts.',
  spentInPeriod:
    'Everything spent in the selected period: money out of spending accounts plus new purchases on credit cards. Internal transfers and card repayments are excluded, so paying off a card never double-counts.',
  paidFromCash:
    'Spending that left your bank accounts directly.',
  chargedToCredit:
    'New purchases on your credit cards — deferred spending you’ll settle later through repayments.',
  forecast:
    'Your spending-account balance projected day by day from today, applying confirmed recurring income, bills, card repayments and planned expenses on their due dates. The lowest point flags any dip below £0 or your overdraft limit.',
  netWorthChange:
    'The difference between your net worth at the start and end of the selected range, from the monthly history below.',
  savingsTotal:
    'The combined balance of accounts marked as “Savings”.',
  assetsTotal:
    'The total of assets you’ve added manually — ISAs, pensions, property — using each asset’s most recent value.',
} as const

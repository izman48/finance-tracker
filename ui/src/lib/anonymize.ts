/** Anonymize numbers: a presentation-layer scrambler for screenshots and
 *  showing the app without exposing your real figures. It is NOT a security
 *  feature — the real data still lives in the browser and API responses. It
 *  protects against shoulder-surfing and screenshots, not device compromise.
 *
 *  How it works: while active, an axios response interceptor walks every
 *  response and (1) multiplies money by a fixed session constant k — linear,
 *  so every total still reconciles — and (2) replaces names with deterministic
 *  pseudonyms (same real name → same fake everywhere). Dates, categories,
 *  counts and ids are untouched. Writes are blocked. See services/api.ts.
 *
 *  Maintenance: MONEY_KEYS / NAME_KEYS below are the whole feature. A new API
 *  field carrying money or a name must be added here or it leaks through when
 *  anonymized. anonymize.test.ts guards this against representative fixtures.
 */

// --- key sets -------------------------------------------------------------- #

// Keys whose value is money — scrambled by ×k. Unambiguous ones scramble
// whether the value is a number or a numeric string.
export const MONEY_KEYS = new Set([
  'amount', 'balance', 'current_balance', 'available_balance', 'value', 'net_worth',
  'bank', 'assets', 'safe_to_spend', 'available_cash', 'credit_owed', 'savable',
  'overdraft_cushion', 'overdraft_limit', 'committed_before_payday', 'savings_total',
  'assets_total', 'total_spent', 'charged_to_credit', 'paid_from_cash',
  'start_balance', 'end_balance', 'min_balance', 'total_amount', 'monthly_amount',
  'repayment_fixed_amount', 'fee_amount',
])

// `total` is money inside spending aggregates (a Decimal string) but a COUNT in
// the transactions-list envelope (an int number). Scramble only the string form.
export const AMBIGUOUS_MONEY_KEYS = new Set(['total'])

// Keys whose value is a person/merchant/brand/bank/account name → pseudonym.
// match_key and pattern carry the real merchant text (a rule/commitment matcher),
// so they must be scrambled too even though they're not shown prominently.
export const NAME_KEYS = new Set([
  'merchant_name', 'description', 'merchant', 'label', 'name',
  'provider_name', 'display_name', 'account', 'match_key', 'pattern',
])

// Keys whose value is an array of names (e.g. the merchant filter facets).
export const NAME_ARRAY_KEYS = new Set(['merchants'])

// Query params that carry a (possibly pseudonymised) name and must be
// translated back to the real value before hitting the server.
export const NAME_PARAM_KEYS = new Set(['merchant', 'search'])

// Query params that carry a money threshold the user typed against a *scrambled*
// figure — divided by k so the server compares against the real amount.
export const MONEY_PARAM_KEYS = new Set(['min_amount', 'max_amount'])

const BANK_KEYS = new Set(['provider_name', 'display_name', 'account'])

const DEMO_EMAIL = 'you@anonymized.example'

// --- deterministic pseudonyms --------------------------------------------- #

const MERCHANT_PREFIX = [
  'Fernwood', 'Brightwater', 'Oakvale', 'Redgate', 'Hollowmere', 'Ashcroft',
  'Silverbrook', 'Thornbury', 'Maplewood', 'Greypoint', 'Larkfield', 'Ravenna',
  'Copperline', 'Mistvale', 'Elmore', 'Pinehurst', 'Wolfden', 'Cindermill',
  'Harlow', 'Bexley', 'Cobalt', 'Verano', 'Sundial', 'Northgate',
]
const MERCHANT_NOUN = [
  'Grocers', 'Market', 'Kitchen', 'Coffee', 'Supplies', 'Trading', 'Provisions',
  'Goods', 'Outfitters', 'Bakehouse', 'Wholesale', 'Emporium', 'Depot',
  'Larder', 'Works', 'Company',
]
const BANK_PREFIX = [
  'Acorn', 'Harbor', 'Meridian', 'Sterling', 'Aldgate', 'Crestline', 'Halcyon',
  'Beacon', 'Ironvale', 'Kestrel', 'Solent', 'Cardinal', 'Everly', 'Bramble',
  'Norwood', 'Pinnacle',
]
const BANK_NOUN = ['Bank', 'Financial', 'Savings', 'Mutual', 'Trust', 'Union']

// Two independent hashes so prefix and noun vary independently — expands the
// pseudonym space and keeps collisions rare while staying deterministic.
function hash(s: string, seed: number): number {
  let h = seed >>> 0
  for (let i = 0; i < s.length; i++) {
    h = (h ^ s.charCodeAt(i)) >>> 0
    h = Math.imul(h, 16777619) >>> 0
  }
  return h >>> 0
}

function pseudonym(real: string, isBank: boolean): string {
  const pre = isBank ? BANK_PREFIX : MERCHANT_PREFIX
  const noun = isBank ? BANK_NOUN : MERCHANT_NOUN
  const a = hash(real, 2166136261)
  const b = hash(real, 63313)
  return `${pre[a % pre.length]} ${noun[b % noun.length]}`
}

// --- money ----------------------------------------------------------------- #

const NUMERIC = /^-?\d+(\.\d+)?$/

const isNumericString = (v: unknown): v is string => typeof v === 'string' && NUMERIC.test(v)

function scrambleMoney(value: unknown, k: number): unknown {
  if (typeof value === 'number') return Math.round(value * k * 100) / 100
  if (isNumericString(value)) return String(Math.round(Number(value) * k * 100) / 100)
  return value // null / non-numeric — leave as-is
}

// --- the walker ------------------------------------------------------------ #

export interface ScrambleCtx {
  k: number
  /** Populated fake→real so outgoing name params can be translated back. */
  reverse?: Map<string, string>
}

function pseudoName(real: string, isBank: boolean, ctx: ScrambleCtx): string {
  const fake = pseudonym(real, isBank)
  ctx.reverse?.set(fake, real)
  return fake
}

/** Recursively scramble a decoded API response in place. Pure w.r.t. globals —
 *  the store supplies k and the reverse map. */
export function scramble(node: unknown, ctx: ScrambleCtx): unknown {
  if (Array.isArray(node)) {
    for (let i = 0; i < node.length; i++) node[i] = scramble(node[i], ctx)
    return node
  }
  if (node && typeof node === 'object') {
    const obj = node as Record<string, unknown>
    for (const key of Object.keys(obj)) {
      const val = obj[key]
      if (MONEY_KEYS.has(key)) {
        obj[key] = scrambleMoney(val, ctx.k)
      } else if (AMBIGUOUS_MONEY_KEYS.has(key)) {
        obj[key] = isNumericString(val) ? scrambleMoney(val, ctx.k) : val
      } else if (NAME_KEYS.has(key) && typeof val === 'string' && val) {
        obj[key] = pseudoName(val, BANK_KEYS.has(key), ctx)
      } else if (key === 'email' && typeof val === 'string') {
        obj[key] = DEMO_EMAIL
      } else if (NAME_ARRAY_KEYS.has(key) && Array.isArray(val)) {
        obj[key] = val.map((x) => (typeof x === 'string' && x ? pseudoName(x, false, ctx) : x))
      } else if (val && typeof val === 'object') {
        obj[key] = scramble(val, ctx)
      }
    }
    return obj
  }
  return node
}

// --- the store (browser-only; guards for the test/node env) ---------------- #

const ON_KEY = 'anon.on'
const K_KEY = 'anon.k'

function ss(): Storage | null {
  try {
    return typeof sessionStorage !== 'undefined' ? sessionStorage : null
  } catch {
    return null
  }
}

let on = ss()?.getItem(ON_KEY) === '1'
let k = Number(ss()?.getItem(K_KEY)) || 1
// A fresh reverse map per page load; rebuilt as scrambled responses arrive.
const reverse = new Map<string, string>()
const listeners = new Set<() => void>()

export const isAnonymized = () => on

export function scrambleResponse(data: unknown): unknown {
  return on ? scramble(data, { k, reverse }) : data
}

/** Translate an outgoing name param (fake → real) so server-side filtering
 *  keeps working while the UI shows pseudonyms. */
export function realParam(value: string): string {
  return reverse.get(value) ?? value
}

/** Translate a money-threshold param typed against a scrambled figure back to
 *  the real scale (÷k), so amount filters select the right rows. */
export function realMoneyParam(shown: string): string {
  const n = Number(shown)
  if (!Number.isFinite(n) || k === 0) return shown
  return String(n / k)
}

export function setAnonymized(next: boolean) {
  const store = ss()
  if (next) {
    // Fresh scale each time it's switched on; k persists across reloads so
    // figures don't jump if a page re-fetches.
    k = Math.round((0.4 + Math.random() * 2.1) * 1000) / 1000
    store?.setItem(ON_KEY, '1')
    store?.setItem(K_KEY, String(k))
  } else {
    store?.removeItem(ON_KEY)
    store?.removeItem(K_KEY)
  }
  on = next
  // A reload is the simplest way to flip the whole app at once: every page
  // re-fetches through the interceptor with the new state.
  if (typeof window !== 'undefined') window.location.reload()
  listeners.forEach((l) => l())
}

export function subscribeAnonymized(l: () => void) {
  listeners.add(l)
  return () => listeners.delete(l)
}

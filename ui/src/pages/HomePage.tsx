import { useLayoutEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import {
  Wallet,
  PieChart,
  TrendingUp,
  SlidersHorizontal,
  Landmark,
  ShieldCheck,
  Lock,
  KeyRound,
  EyeOff,
  Shuffle,
  Trash2,
  Building2,
  Sparkles,
} from 'lucide-react'
import { useAuth } from '../hooks/useAuth'
import { gbp0 as gbp } from '../lib/format'

gsap.registerPlugin(ScrollTrigger)

/** Static preview of the dashboard, built from the real design system. */
function HeroPreview() {
  const bars = [62, 38, 81, 55, 47, 70, 90]
  return (
    <div className="card p-5 sm:p-6 w-full max-w-md mx-auto" data-hero="preview">
      <div className="text-xs text-slate-500 mb-1">Safe to spend until payday</div>
      <div className="stat-figure text-4xl text-slate-50" data-hero="amount">
        {gbp(1247)}
      </div>
      <div className="mt-4 flex items-end gap-1.5 h-20" aria-hidden>
        {bars.map((h, i) => (
          <div
            key={i}
            data-hero="bar"
            className={`flex-1 rounded-t-md ${i === bars.length - 1 ? 'bg-accent' : 'bg-accent/25'}`}
            style={{ height: `${h}%` }}
          />
        ))}
      </div>
      <div className="mt-4 pt-4 border-t border-white/[0.06] space-y-2 text-sm">
        {[
          { label: 'Rent', amount: -1100, date: '1 Jul' },
          { label: 'Salary', amount: 3200, date: '28 Jun' },
          { label: 'Credit card bill', amount: -430, date: '15 Jun' },
        ].map((r) => (
          <div key={r.label} className="flex items-center justify-between" data-hero="row">
            <span className="text-slate-300">{r.label}</span>
            <span className="tnum">
              <span className={r.amount > 0 ? 'text-pos' : 'text-slate-400'}>
                {r.amount > 0 ? '+' : ''}
                {gbp(r.amount)}
              </span>
              <span className="text-slate-600 text-xs ml-2">{r.date}</span>
            </span>
          </div>
        ))}
      </div>
      {/* The wealth story, above the fold. */}
      <div className="mt-3 pt-3 border-t border-white/[0.06] flex items-center justify-between text-sm" data-hero="row">
        <span className="text-slate-500">Net worth</span>
        <span className="tnum font-semibold text-slate-100">
          {gbp(84350)} <span className="text-pos text-xs">▲</span>
        </span>
      </div>
    </div>
  )
}

// The three questions the app answers — mirroring its three tabs.
const FEATURES = [
  {
    icon: Wallet,
    title: 'How much can I spend?',
    body: 'One honest number — cash minus every bill and repayment before payday — plus a day-by-day balance forecast up to a year ahead.',
  },
  {
    icon: PieChart,
    title: 'Where did it go?',
    body: 'Spending by category, merchant and month, with cash and credit kept honest and separate — and every figure opens the transactions behind it.',
  },
  {
    icon: TrendingUp,
    title: 'Am I getting richer?',
    body: 'Your whole balance sheet: bank accounts update live via open banking, with ISAs, pensions, property and crypto alongside.',
  },
]

const SUPPORTING = [
  {
    icon: SlidersHorizontal,
    title: 'Categorise once',
    body: 'Rules tidy every future sync automatically, and you can share rule packs with friends.',
  },
  {
    icon: Landmark,
    title: 'As many banks as you like',
    body: 'Connect your current accounts, savings and credit cards via TrueLayer open banking.',
  },
]

const SECURITY = [
  {
    icon: Building2,
    title: 'Read-only open banking',
    body: 'We connect through TrueLayer, an FCA-authorised open-banking provider. You log in on your bank’s own page — we never see or store your banking password, and the connection can only read, never move money.',
  },
  {
    icon: Lock,
    title: 'Encrypted with your key, not ours',
    body: 'Your transactions, balances and bank details are encrypted with a key derived from your password — we can’t read them, even with full access to our own database. Bank tokens carry a second server-side layer on top.',
  },
  {
    icon: KeyRound,
    title: 'Your key, your responsibility too',
    body: 'Because only your password unlocks your data, you get a one-time recovery code at sign-up. Reset your password with it and everything survives; lose both and your data can’t be recovered — you reconnect your bank and start fresh. Passwords are stored only as salted bcrypt hashes, and everything runs over HTTPS with HSTS.',
  },
  {
    icon: EyeOff,
    title: 'Your data is never sold',
    body: 'Your finances are yours. We don’t sell or share your data, and we don’t run third-party ad or tracking scripts on your dashboard.',
  },
  {
    icon: Trash2,
    title: 'Leave whenever you want',
    body: 'Disconnect a bank in one click, or delete your account and every transaction permanently — no emails, no retention games.',
  },
  {
    icon: ShieldCheck,
    title: 'Built to be audited',
    body: 'Scoped access tokens, least-privilege data access, and a security model we review on every change — built with future FCA-grade scrutiny in mind.',
  },
  {
    icon: Sparkles,
    title: 'A fresh start, on purpose',
    body: 'In July 2026 we reset our databases to launch per-user encryption. Data collected under the old model was deleted rather than migrated, so nothing about you sits in our systems that isn’t protected by your key.',
  },
  {
    icon: Shuffle,
    title: 'Show the app, not your numbers',
    body: 'One tap anonymizes every figure and name — hand someone your phone or take a screenshot without revealing a thing. It’s a privacy convenience, not a security layer: your real data still lives safely behind your key.',
  },
]

export default function HomePage() {
  const { isAuthenticated } = useAuth()
  const root = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const ctx = gsap.context(() => {
      const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
      tl.from('[data-hero="kicker"]', { y: 16, opacity: 0, duration: 0.5 })
        .from('[data-hero="title"]', { y: 24, opacity: 0, duration: 0.7 }, '-=0.25')
        .from('[data-hero="sub"]', { y: 18, opacity: 0, duration: 0.6 }, '-=0.4')
        .from('[data-hero="cta"]', { y: 14, opacity: 0, duration: 0.5 }, '-=0.35')
        .from('[data-hero="preview"]', { y: 30, opacity: 0, duration: 0.8 }, '-=0.3')
        .from('[data-hero="bar"]', { scaleY: 0, transformOrigin: 'bottom', stagger: 0.06, duration: 0.5 }, '-=0.5')
        .from('[data-hero="row"]', { x: -12, opacity: 0, stagger: 0.1, duration: 0.4 }, '-=0.3')
      gsap.from('[data-feature]', {
        y: 24,
        opacity: 0,
        stagger: 0.08,
        duration: 0.6,
        ease: 'power2.out',
        delay: 0.5,
      })
      // Security section reveals on scroll into view.
      gsap.from('[data-sec]', {
        scrollTrigger: { trigger: '[data-sec]', start: 'top 85%' },
        y: 24,
        opacity: 0,
        stagger: 0.08,
        duration: 0.6,
        ease: 'power2.out',
      })
    }, root)
    return () => ctx.revert()
  }, [])

  return (
    <div ref={root} className="relative overflow-hidden">
      {/* Ambient orbs */}
      <div className="orb w-[36rem] h-[36rem] bg-accent/15 -top-48 -right-40 animate-float-slow" />
      <div className="orb w-[28rem] h-[28rem] bg-sky2/10 top-64 -left-48 animate-float-slower" />

      <div className="relative max-w-7xl mx-auto px-4 pt-14 sm:pt-24 pb-16">
        <div className="grid lg:grid-cols-2 gap-12 items-center">
          <div className="text-center lg:text-left">
            <div data-hero="kicker" className="chip-pos mb-5">
              Open banking · your data stays yours
            </div>
            <h1
              data-hero="title"
              className="font-display font-bold tracking-tight text-4xl sm:text-5xl lg:text-6xl text-slate-50 leading-[1.05] mb-6"
            >
              Know what's truly{' '}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-accent to-sky2">
                safe to spend
              </span>
            </h1>
            <p data-hero="sub" className="text-lg text-slate-400 max-w-xl mx-auto lg:mx-0 mb-8">
              Connect your banks and see one honest picture: what you can spend, where it went,
              and what you're worth — before payday catches you out.
            </p>
            <div data-hero="cta" className="flex flex-wrap gap-3 justify-center lg:justify-start">
              {isAuthenticated ? (
                <Link to="/dashboard" className="btn-primary !px-7 !py-3 !text-base">
                  Go to dashboard
                </Link>
              ) : (
                <>
                  <Link to="/register" className="btn-primary !px-7 !py-3 !text-base">
                    Get started free
                  </Link>
                  <Link to="/login" className="btn-ghost !px-7 !py-3 !text-base">
                    Log in
                  </Link>
                </>
              )}
            </div>
          </div>

          <HeroPreview />
        </div>

        <div className="mt-20 sm:mt-28 grid grid-cols-1 md:grid-cols-3 gap-4 sm:gap-5">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <div key={title} data-feature className="card-pad hover:border-accent/25 transition-colors">
              <span className="w-10 h-10 rounded-xl bg-accent/15 border border-accent/20 flex items-center justify-center mb-4">
                <Icon className="w-5 h-5 text-accent" />
              </span>
              <h3 className="font-display font-semibold text-slate-100 mb-1.5">{title}</h3>
              <p className="text-sm text-slate-400 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>
        <div className="mt-4 sm:mt-5 grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-5">
          {SUPPORTING.map(({ icon: Icon, title, body }) => (
            <div key={title} data-feature className="card p-4 flex items-start gap-3 hover:border-accent/25 transition-colors">
              <span className="w-9 h-9 shrink-0 rounded-xl bg-white/[0.06] flex items-center justify-center">
                <Icon className="w-4 h-4 text-slate-400" />
              </span>
              <span className="min-w-0">
                <span className="block font-display font-semibold text-sm text-slate-100">{title}</span>
                <span className="block text-sm text-slate-400 leading-relaxed">{body}</span>
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Security */}
      <div className="relative border-t border-white/[0.06] bg-ink-950/40">
        <div className="relative max-w-7xl mx-auto px-4 py-16 sm:py-24">
          <div className="max-w-2xl mb-12">
            <div data-sec className="inline-flex items-center gap-2 chip-pos mb-5">
              <ShieldCheck className="w-3.5 h-3.5" />
              Security
            </div>
            <h2
              data-sec
              className="font-display font-bold tracking-tight text-3xl sm:text-4xl text-slate-50 mb-4"
            >
              Built for money you can't afford to lose
            </h2>
            <p data-sec className="text-lg text-slate-400">
              You're trusting us with a window into your finances. Here's exactly how we protect it —
              and what we'll never do with it.
            </p>
          </div>

          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-5">
            {SECURITY.map(({ icon: Icon, title, body }) => (
              <div key={title} data-sec className="card-pad hover:border-accent/25 transition-colors">
                <span className="w-10 h-10 rounded-xl bg-accent/15 border border-accent/20 flex items-center justify-center mb-4">
                  <Icon className="w-5 h-5 text-accent" />
                </span>
                <h3 className="font-display font-semibold text-slate-100 mb-1.5">{title}</h3>
                <p className="text-sm text-slate-400 leading-relaxed">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

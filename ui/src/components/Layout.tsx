import { useEffect, useRef, useState } from 'react'
import { Outlet, Link, NavLink, useLocation } from 'react-router-dom'
import {
  Wallet,
  ArrowLeftRight,
  PieChart,
  CalendarClock,
  TrendingUp,
  SlidersHorizontal,
  LogOut,
  ChevronDown,
} from 'lucide-react'
import { useAuth } from '../hooks/useAuth'

const NAV_LINKS = [
  { to: '/dashboard', label: 'Today', icon: Wallet },
  { to: '/transactions', label: 'Activity', icon: ArrowLeftRight },
  { to: '/insights', label: 'Spending', icon: PieChart },
  { to: '/commitments', label: 'Plan', icon: CalendarClock },
  { to: '/networth', label: 'Wealth', icon: TrendingUp },
  { to: '/rules', label: 'Rules', icon: SlidersHorizontal },
]

// The five tabs that fit a thumb-friendly mobile bar; Rules lives in the user menu.
const MOBILE_TABS = NAV_LINKS.slice(0, 5)

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5 group">
      <span className="w-8 h-8 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center transition-shadow group-hover:shadow-glow">
        <svg viewBox="0 0 64 64" className="w-5 h-5">
          <path
            d="M14 44 L26 32 L34 38 L50 20"
            fill="none"
            stroke="#2DD4A7"
            strokeWidth="7"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle cx="50" cy="20" r="6" fill="#4AE3BB" />
        </svg>
      </span>
      <span className="font-display font-bold text-xl text-slate-100 tracking-tight">
        nilu<span className="text-accent">.</span>
      </span>
    </Link>
  )
}

function UserMenu() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 px-2.5 py-1.5 rounded-xl hover:bg-white/[0.06] transition-colors"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="w-7 h-7 rounded-full bg-gradient-to-br from-accent/60 to-sky2/60 flex items-center justify-center text-xs font-bold text-ink-950 uppercase">
          {user?.email?.[0] ?? '?'}
        </span>
        <ChevronDown className="w-4 h-4 text-slate-500" />
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-60 card p-2 z-50">
          <div className="px-3 py-2 text-xs text-slate-500 truncate">{user?.email}</div>
          <NavLink
            to="/rules"
            onClick={() => setOpen(false)}
            className="lg:hidden flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-slate-300 hover:bg-white/[0.06]"
          >
            <SlidersHorizontal className="w-4 h-4" /> Rules
          </NavLink>
          <button
            onClick={() => {
              setOpen(false)
              logout()
            }}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-slate-300 hover:bg-white/[0.06] hover:text-neg"
          >
            <LogOut className="w-4 h-4" /> Log out
          </button>
        </div>
      )}
    </div>
  )
}

export default function Layout() {
  const { isAuthenticated } = useAuth()
  const location = useLocation()

  // Scroll back to the top on page change (mobile tab switches especially).
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [location.pathname])

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-40 bg-ink-900/80 backdrop-blur-xl border-b border-white/[0.06]">
        <nav className="max-w-7xl mx-auto px-4 h-16 flex justify-between items-center">
          <Logo />

          {isAuthenticated ? (
            <>
              {/* Desktop nav (lg+: tablets keep the bottom tab bar) */}
              <div className="hidden lg:flex items-center gap-1">
                {NAV_LINKS.map(({ to, label, icon: Icon }) => (
                  <NavLink
                    key={to}
                    to={to}
                    className={({ isActive }) =>
                      `flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-sm transition-colors ${
                        isActive
                          ? 'bg-accent/15 text-accent font-medium'
                          : 'text-slate-400 hover:text-slate-100 hover:bg-white/[0.06]'
                      }`
                    }
                  >
                    <Icon className="w-4 h-4" />
                    {label}
                  </NavLink>
                ))}
              </div>
              <UserMenu />
            </>
          ) : (
            <div className="flex items-center gap-2">
              <Link to="/login" className="btn-ghost">
                Log in
              </Link>
              <Link to="/register" className="btn-primary">
                Get started
              </Link>
            </div>
          )}
        </nav>
      </header>

      <main className={`flex-1 ${isAuthenticated ? 'pb-24 lg:pb-0' : ''}`}>
        <Outlet />
      </main>

      {/* Mobile bottom tab bar */}
      {isAuthenticated && (
        <nav
          className="lg:hidden fixed bottom-0 inset-x-0 z-40 bg-ink-900/90 backdrop-blur-xl border-t border-white/[0.08] safe-bottom"
          aria-label="Primary"
        >
          <div className="grid grid-cols-5">
            {MOBILE_TABS.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `flex flex-col items-center gap-1 py-2.5 text-[11px] transition-colors ${
                    isActive ? 'text-accent' : 'text-slate-500 hover:text-slate-300'
                  }`
                }
              >
                <Icon className="w-5 h-5" strokeWidth={2} />
                {label}
              </NavLink>
            ))}
          </div>
        </nav>
      )}

      <footer className={`border-t border-white/[0.06] py-8 ${isAuthenticated ? 'hidden lg:block' : ''}`}>
        <div className="max-w-7xl mx-auto px-4 text-center text-sm text-slate-600">
          nilu. — know what you have, where it went, and what's coming.
        </div>
      </footer>
    </div>
  )
}

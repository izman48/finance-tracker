import { useState } from 'react'
import { Outlet, Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

const NAV_LINKS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/insights', label: 'Spending' },
  { to: '/commitments', label: 'Commitments' },
]

export default function Layout() {
  const { isAuthenticated, logout, user } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white shadow-sm">
        <nav className="max-w-7xl mx-auto px-4 py-4 flex justify-between items-center">
          <Link to="/" className="text-xl font-bold text-blue-600">
            Finance Tracker
          </Link>

          {/* Desktop nav */}
          <div className="hidden md:flex items-center gap-4">
            {isAuthenticated ? (
              <>
                {NAV_LINKS.map((link) => (
                  <Link key={link.to} to={link.to} className="text-gray-700 hover:text-blue-600">
                    {link.label}
                  </Link>
                ))}
                <span className="text-gray-600 ml-2 hidden lg:inline">{user?.email}</span>
                <button
                  onClick={logout}
                  className="px-4 py-2 text-gray-700 hover:text-red-600"
                >
                  Logout
                </button>
              </>
            ) : (
              <>
                <Link to="/login" className="text-gray-700 hover:text-blue-600">
                  Login
                </Link>
                <Link
                  to="/register"
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                >
                  Get Started
                </Link>
              </>
            )}
          </div>

          {/* Mobile menu button */}
          <button
            className="md:hidden p-2 text-gray-700 hover:text-blue-600"
            onClick={() => setMenuOpen((open) => !open)}
            aria-label="Toggle menu"
            aria-expanded={menuOpen}
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {menuOpen ? (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              )}
            </svg>
          </button>
        </nav>

        {/* Mobile nav */}
        {menuOpen && (
          <div className="md:hidden border-t border-gray-100 px-4 py-3 space-y-1 bg-white">
            {isAuthenticated ? (
              <>
                {NAV_LINKS.map((link) => (
                  <Link
                    key={link.to}
                    to={link.to}
                    onClick={() => setMenuOpen(false)}
                    className="block py-2 text-gray-700 hover:text-blue-600"
                  >
                    {link.label}
                  </Link>
                ))}
                <div className="pt-2 mt-2 border-t border-gray-100 flex items-center justify-between">
                  <span className="text-sm text-gray-500 truncate">{user?.email}</span>
                  <button
                    onClick={() => {
                      setMenuOpen(false)
                      logout()
                    }}
                    className="py-2 pl-4 text-gray-700 hover:text-red-600"
                  >
                    Logout
                  </button>
                </div>
              </>
            ) : (
              <>
                <Link
                  to="/login"
                  onClick={() => setMenuOpen(false)}
                  className="block py-2 text-gray-700 hover:text-blue-600"
                >
                  Login
                </Link>
                <Link
                  to="/register"
                  onClick={() => setMenuOpen(false)}
                  className="block py-2 text-blue-600 font-medium"
                >
                  Get Started
                </Link>
              </>
            )}
          </div>
        )}
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      <footer className="bg-gray-100 py-6">
        <div className="max-w-7xl mx-auto px-4 text-center text-gray-600">
          <p>Finance Tracker - Understand where your money goes</p>
        </div>
      </footer>
    </div>
  )
}

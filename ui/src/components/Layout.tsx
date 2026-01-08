import { Outlet, Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export default function Layout() {
  const { isAuthenticated, logout, user } = useAuth()

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white shadow-sm">
        <nav className="max-w-7xl mx-auto px-4 py-4 flex justify-between items-center">
          <Link to="/" className="text-xl font-bold text-blue-600">
            Finance Tracker
          </Link>

          <div className="flex items-center gap-4">
            {isAuthenticated ? (
              <>
                <Link
                  to="/dashboard"
                  className="text-gray-700 hover:text-blue-600"
                >
                  Dashboard
                </Link>
                <Link
                  to="/transactions"
                  className="text-gray-700 hover:text-blue-600"
                >
                  Transactions
                </Link>
                <Link
                  to="/insights"
                  className="text-gray-700 hover:text-blue-600"
                >
                  Insights
                </Link>
                <span className="text-gray-600 ml-2">{user?.email}</span>
                <button
                  onClick={logout}
                  className="px-4 py-2 text-gray-700 hover:text-red-600"
                >
                  Logout
                </button>
              </>
            ) : (
              <>
                <Link
                  to="/login"
                  className="text-gray-700 hover:text-blue-600"
                >
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
        </nav>
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

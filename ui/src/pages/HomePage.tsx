import { Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export default function HomePage() {
  const { isAuthenticated } = useAuth()

  return (
    <div className="max-w-7xl mx-auto px-4 py-10 sm:py-16">
      <div className="text-center">
        <h1 className="text-3xl sm:text-5xl font-bold text-gray-900 mb-6">
          Understand Where Your Money Goes
        </h1>
        <p className="text-lg sm:text-xl text-gray-600 mb-8 max-w-2xl mx-auto">
          Connect your bank accounts and get insights into your spending patterns,
          recurring payments, and the opportunity cost of your expenses.
        </p>

        {isAuthenticated ? (
          <Link
            to="/dashboard"
            className="inline-block px-8 py-4 bg-blue-600 text-white text-lg font-semibold rounded-lg hover:bg-blue-700"
          >
            Go to Dashboard
          </Link>
        ) : (
          <Link
            to="/register"
            className="inline-block px-8 py-4 bg-blue-600 text-white text-lg font-semibold rounded-lg hover:bg-blue-700"
          >
            Get Started Free
          </Link>
        )}
      </div>

      <div className="mt-12 sm:mt-20 grid md:grid-cols-3 gap-6 sm:gap-8">
        <div className="p-6 bg-white rounded-xl shadow-sm">
          <h3 className="text-xl font-semibold mb-3">📊 Spending Analysis</h3>
          <p className="text-gray-600">
            Categorize and visualize your transactions to see exactly where your
            money is going.
          </p>
        </div>

        <div className="p-6 bg-white rounded-xl shadow-sm">
          <h3 className="text-xl font-semibold mb-3">🔄 Recurring Payments</h3>
          <p className="text-gray-600">
            Automatically detect subscriptions and recurring expenses you might
            have forgotten about.
          </p>
        </div>

        <div className="p-6 bg-white rounded-xl shadow-sm">
          <h3 className="text-xl font-semibold mb-3">💷 Safe to Spend</h3>
          <p className="text-gray-600">
            Know exactly what you can spend before payday, after every bill and
            repayment is accounted for.
          </p>
        </div>
      </div>
    </div>
  )
}

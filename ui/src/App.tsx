import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './hooks/useAuth'
import { ToastProvider } from './components/ui/Toast'
import { ConfirmProvider } from './components/ui/ConfirmDialog'
import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import ResetPasswordPage from './pages/ResetPasswordPage'
import DashboardPage from './pages/DashboardPage'
import TransactionsPage from './pages/TransactionsPage'
import InsightsPage from './pages/InsightsPage'
import CommitmentsPage from './pages/CommitmentsPage'
import RulesPage from './pages/RulesPage'
import NetWorthPage from './pages/NetWorthPage'
import ImportSharedPage from './pages/ImportSharedPage'
import CallbackPage from './pages/CallbackPage'
import ProtectedRoute from './components/ProtectedRoute'

function App() {
  return (
    <AuthProvider>
      <ToastProvider>
      <ConfirmProvider>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="login" element={<LoginPage />} />
          <Route path="register" element={<RegisterPage />} />
          <Route path="forgot-password" element={<ForgotPasswordPage />} />
          <Route path="reset-password" element={<ResetPasswordPage />} />
          <Route
            path="dashboard"
            element={
              <ProtectedRoute>
                <DashboardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="transactions"
            element={
              <ProtectedRoute>
                <TransactionsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="insights"
            element={
              <ProtectedRoute>
                <InsightsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="commitments"
            element={
              <ProtectedRoute>
                <CommitmentsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="networth"
            element={
              <ProtectedRoute>
                <NetWorthPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="rules"
            element={
              <ProtectedRoute>
                <RulesPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="r/:code"
            element={
              <ProtectedRoute>
                <ImportSharedPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="callback"
            element={
              <ProtectedRoute>
                <CallbackPage />
              </ProtectedRoute>
            }
          />
        </Route>
      </Routes>
      </ConfirmProvider>
      </ToastProvider>
    </AuthProvider>
  )
}

export default App

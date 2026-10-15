import { Link, useLocation } from 'react-router-dom'

/** Any path the app doesn't know (T-12-12). The path is shown as plain text
 *  (React escapes it), never as markup or a link. */
export default function NotFoundPage() {
  const { pathname } = useLocation()
  return (
    <div className="max-w-xl mx-auto px-4 py-16 text-center">
      <h1 className="font-display font-bold text-2xl text-slate-50 mb-2">Page not found</h1>
      <p className="text-sm text-slate-400 mb-6 break-words">
        There is no page at <span className="text-slate-300">{pathname}</span>.
      </p>
      <Link to="/home" className="btn-primary inline-flex">Go to Home</Link>
    </div>
  )
}

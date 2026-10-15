import axios from 'axios'

/** The page message when starting a bank connection fails: empty for a
 *  demo-mode block (the toast already says why, T-12-11), else the server's
 *  detail or the error message. */
export function bankLinkError(prefix: string, error: unknown): string {
  if (axios.isCancel(error)) return ''
  const e = error as { response?: { data?: { detail?: unknown } }; message?: string }
  return `${prefix}: ${String(e.response?.data?.detail ?? e.message ?? 'unknown error')}`
}

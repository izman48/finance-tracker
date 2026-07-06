import { createContext, useCallback, useContext, useRef, useState, ReactNode } from 'react'

interface ToastAction {
  label: string
  onClick: () => void
}

interface ToastOptions {
  tone?: 'ok' | 'err'
  action?: ToastAction
}

interface ToastState {
  message: string
  tone: 'ok' | 'err'
  action?: ToastAction
}

type ShowToast = (message: string, options?: ToastOptions) => void

const ToastContext = createContext<ShowToast>(() => {})

/** App-wide toast: one at a time, auto-dismisses, optional action button. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null)
  const timer = useRef<number>()

  const show = useCallback<ShowToast>((message, options) => {
    window.clearTimeout(timer.current)
    setToast({ message, tone: options?.tone ?? 'ok', action: options?.action })
    timer.current = window.setTimeout(() => setToast(null), 3500)
  }, [])

  return (
    <ToastContext.Provider value={show}>
      {children}
      {toast && (
        <div
          role="status"
          className={`fixed bottom-24 md:bottom-6 right-4 sm:right-6 z-50 flex items-center gap-3 font-medium px-4 py-3 rounded-xl shadow-pop text-ink-950 ${
            toast.tone === 'err' ? 'bg-neg' : 'bg-accent'
          }`}
        >
          {toast.message}
          {toast.action && (
            <button
              onClick={() => {
                window.clearTimeout(timer.current)
                setToast(null)
                toast.action!.onClick()
              }}
              className="underline underline-offset-2 whitespace-nowrap"
            >
              {toast.action.label}
            </button>
          )}
        </div>
      )}
    </ToastContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components -- provider + hook intentionally share a file
export const useToast = () => useContext(ToastContext)

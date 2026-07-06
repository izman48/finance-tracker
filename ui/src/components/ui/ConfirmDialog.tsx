import { createContext, useCallback, useContext, useState, ReactNode } from 'react'

interface ConfirmOptions {
  title: string
  body?: string
  confirmLabel?: string
  danger?: boolean
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>

const ConfirmContext = createContext<Confirm>(() => Promise.resolve(false))

/** Promise-based confirm dialog replacing native confirm(). */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<{
    options: ConfirmOptions
    resolve: (v: boolean) => void
  } | null>(null)

  const confirm = useCallback<Confirm>(
    (options) => new Promise<boolean>((resolve) => setPending({ options, resolve })),
    [],
  )

  const close = (result: boolean) => {
    pending?.resolve(result)
    setPending(null)
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && (
        <div className="modal-backdrop" onClick={() => close(false)}>
          <div
            className="modal-panel !max-w-sm"
            role="alertdialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-slate-50 mb-2">{pending.options.title}</h3>
            {pending.options.body && (
              <p className="text-sm text-slate-400 mb-4">{pending.options.body}</p>
            )}
            <div className="flex justify-end gap-2 mt-2">
              <button onClick={() => close(false)} className="btn-ghost" autoFocus>
                Cancel
              </button>
              <button
                onClick={() => close(true)}
                className={pending.options.danger ? 'btn-danger' : 'btn-primary'}
              >
                {pending.options.confirmLabel ?? 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components -- provider + hook intentionally share a file
export const useConfirm = () => useContext(ConfirmContext)

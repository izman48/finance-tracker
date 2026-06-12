import { ReactNode } from 'react'

/** Centered card used by all auth pages, with ambient glow. */
export default function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: string
  children: ReactNode
}) {
  return (
    <div className="relative overflow-hidden min-h-[70vh] flex items-center justify-center px-4 py-16">
      <div className="orb w-96 h-96 bg-accent/15 -top-20 right-1/4 animate-float-slow" />
      <div className="orb w-80 h-80 bg-sky2/10 bottom-0 left-1/4 animate-float-slower" />
      <div className="relative w-full max-w-md card p-7 sm:p-9 animate-fade-up">
        <h1 className="font-display font-bold text-2xl text-slate-50 mb-1.5">{title}</h1>
        {subtitle && <p className="text-sm text-slate-400 mb-6">{subtitle}</p>}
        {!subtitle && <div className="mb-6" />}
        {children}
      </div>
    </div>
  )
}

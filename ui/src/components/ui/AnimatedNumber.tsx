import { useEffect, useRef } from 'react'
import gsap from 'gsap'

const prefersReducedMotion = () =>
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * Counts up to `value` with GSAP. Formats as GBP by default; pass a custom
 * `format` for anything else. Falls back to a static value for reduced motion.
 */
export default function AnimatedNumber({
  value,
  format,
  duration = 1.1,
  className,
}: {
  value: number
  format?: (n: number) => string
  duration?: number
  className?: string
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const fmt =
    format ??
    ((n: number) =>
      new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(n))

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (prefersReducedMotion()) {
      el.textContent = fmt(value)
      return
    }
    const state = { n: 0 }
    const tween = gsap.to(state, {
      n: value,
      duration,
      ease: 'power2.out',
      onUpdate: () => {
        el.textContent = fmt(state.n)
      },
    })
    return () => {
      tween.kill()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  return (
    <span ref={ref} className={className}>
      {fmt(0)}
    </span>
  )
}

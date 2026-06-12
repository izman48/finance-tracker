import { useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'

/**
 * Staggered entrance for everything marked `data-reveal` inside the returned
 * container ref. Re-runs when `ready` flips to true (e.g. after data loads).
 */
export default function useReveal<T extends HTMLElement = HTMLDivElement>(ready = true) {
  const ref = useRef<T>(null)

  useLayoutEffect(() => {
    if (!ready || !ref.current) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const targets = ref.current.querySelectorAll('[data-reveal]')
    if (!targets.length) return
    const ctx = gsap.context(() => {
      gsap.fromTo(
        targets,
        { y: 18, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.55, ease: 'power2.out', stagger: 0.07, clearProps: 'all' },
      )
    }, ref)
    return () => ctx.revert()
  }, [ready])

  return ref
}

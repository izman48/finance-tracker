import { useEffect } from 'react'
import { useToast } from './ui/Toast'

/** Turns a blocked write while anonymized into a toast. The interceptor can't
 *  reach the React toast directly, so it dispatches a window event. */
export default function AnonymizeListener() {
  const showToast = useToast()
  useEffect(() => {
    const onBlocked = (e: Event) => showToast(
      (e as CustomEvent).detail === 'connect' ? 'Demo mode: connecting a bank is off.' : 'Demo mode: nothing was saved.',
      { tone: 'info' },
    )
    window.addEventListener('anonymize:blocked', onBlocked)
    return () => window.removeEventListener('anonymize:blocked', onBlocked)
  }, [showToast])
  return null
}

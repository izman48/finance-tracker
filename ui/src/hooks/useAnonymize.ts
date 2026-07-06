import { useSyncExternalStore } from 'react'
import { isAnonymized, setAnonymized, subscribeAnonymized } from '../lib/anonymize'

/** Subscribe to anonymize state and toggle it. Toggling reloads the app so the
 *  whole UI flips between real and anonymized data at once. */
export function useAnonymize() {
  const anonymized = useSyncExternalStore(subscribeAnonymized, isAnonymized, () => false)
  return { anonymized, toggle: () => setAnonymized(!anonymized), setAnonymized }
}

/**
 * Where `npm run dev` listens (T-08-15). This machine only by default: a dev
 * server on the LAN serves the app, and its API proxying, to anyone on the
 * network. Set VITE_DEV_LAN=1 to test from a phone on the same network.
 */
export function devServerHost(env: Record<string, string | undefined>): string {
  return env.VITE_DEV_LAN === '1' ? '0.0.0.0' : '127.0.0.1'
}

/**
 * Where to send someone after they log in: back to the protected page that
 * bounced them (e.g. the MCP consent page, query intact), else Home.
 * Only same-site absolute paths — anything that could resolve to another
 * origin would turn login into an open redirect.
 */
export function safeReturnPath(from: { pathname?: string; search?: string } | null | undefined): string {
  const path = from?.pathname
  if (!path || !path.startsWith('/') || path.startsWith('//') || path.includes('\\')) return '/home'
  if (path === '/login' || path === '/register') return '/home'
  return path + (from?.search ?? '')
}

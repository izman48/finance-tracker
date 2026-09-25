/**
 * How an AI assistant reaches this deployment's MCP server. Built from the
 * origin the app is served on, so the repo never hard-codes a domain.
 */
export function mcpServerUrl(origin: string): string {
  return `${origin.replace(/\/+$/, '')}/mcp`
}

export function claudeCodeCommand(origin: string): string {
  return `claude mcp add --transport http nilu ${mcpServerUrl(origin)}`
}

import { describe, it, expect } from 'vitest'
import { mcpServerUrl, claudeCodeCommand } from './mcp'

describe('MCP connect details — built from wherever the app is served', () => {
  it('points at /mcp on this origin', () => {
    expect(mcpServerUrl('https://nilu.example')).toBe('https://nilu.example/mcp')
  })

  it('tolerates a trailing slash', () => {
    expect(mcpServerUrl('https://nilu.example/')).toBe('https://nilu.example/mcp')
  })

  it('gives a ready-to-paste Claude Code command', () => {
    expect(claudeCodeCommand('https://nilu.example')).toBe(
      'claude mcp add --transport http nilu https://nilu.example/mcp',
    )
  })
})

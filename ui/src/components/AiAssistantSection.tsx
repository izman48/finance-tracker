import { useState } from 'react'
import { Bot, Check, Copy, KeyRound, MessageSquare, ShieldCheck } from 'lucide-react'
import { claudeCodeCommand, mcpServerUrl } from '../lib/mcp'

const POINTS = [
  {
    icon: MessageSquare,
    title: 'Ask it anything',
    body: '“Which month was my heaviest, and why?” “Can I afford this holiday?” It reads the same numbers you see: forecast, spending, commitments, rules.',
  },
  {
    icon: KeyRound,
    title: 'Sign in once',
    body: 'Approve it on a nilu. page in your browser. No API keys to copy, and it stays connected while you use it.',
  },
  {
    icon: ShieldCheck,
    title: 'Read-only, on your terms',
    body: 'It can’t move money or edit anything you’ve set. The one thing it can add, if you allow it, is a new rule pack. Rule packs can recategorise transactions but never ones you categorised by hand, and you can delete a pack in Rules.',
  },
]

/** A sample exchange, built from the design system. Illustrative figures only. */
function ChatPreview() {
  return (
    <div className="card p-5 sm:p-6 w-full max-w-md mx-auto space-y-4" aria-hidden data-ai>
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-md bg-accent/15 border border-accent/20 px-4 py-2.5 text-sm text-slate-100">
          Which month was my heaviest this year, and why?
        </p>
      </div>
      <div className="flex gap-3">
        <span className="w-8 h-8 shrink-0 rounded-xl bg-white/[0.06] flex items-center justify-center">
          <Bot className="w-4 h-4 text-accent" />
        </span>
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap gap-1.5">
            <span className="chip-info">spending_trend</span>
            <span className="chip-info">spending</span>
          </div>
          <p className="text-sm text-slate-300 leading-relaxed">
            March, at <span className="tnum text-slate-100">£2,840</span>: about{' '}
            <span className="tnum text-slate-100">£900</span> above your usual month. Most of the gap is a{' '}
            <span className="tnum text-slate-100">£640</span> flight booking and your annual car insurance. Groceries and
            eating out were normal.
          </p>
        </div>
      </div>
    </div>
  )
}

function ConnectBox() {
  const origin = window.location.origin
  const command = claudeCodeCommand(origin)
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard can be blocked (permissions, insecure context); the command stays selectable.
    }
  }

  return (
    <div className="card p-4 sm:p-5 space-y-3" data-ai>
      <div className="text-xs uppercase tracking-wide text-slate-500">Claude Code</div>
      <div className="flex items-center gap-2 rounded-xl bg-ink-950/60 border border-white/[0.06] pl-3 pr-1.5 py-1.5">
        <code className="min-w-0 flex-1 break-all text-xs sm:text-sm text-slate-200 font-mono select-all">
          {command}
        </code>
        <button
          type="button"
          onClick={copy}
          className="btn-ghost shrink-0 !px-2.5 !py-1.5"
          aria-label={copied ? 'Copied' : 'Copy command'}
        >
          {copied ? <Check className="w-4 h-4 text-accent" /> : <Copy className="w-4 h-4" />}
        </button>
      </div>
      <p className="text-xs text-slate-400 leading-relaxed">
        <span className="text-slate-300">Claude Desktop</span> and other MCP clients that support sign-in: add{' '}
        <code className="font-mono text-slate-200 break-all">{mcpServerUrl(origin)}</code> as a custom connector.
      </p>
    </div>
  )
}

/** Landing-page section advertising the remote MCP server. */
export default function AiAssistantSection() {
  return (
    <div className="relative border-t border-white/[0.06]">
      <div className="relative max-w-7xl mx-auto px-4 py-16 sm:py-24">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
          <div>
            <div data-ai className="inline-flex items-center gap-2 chip-pos mb-5">
              <Bot className="w-3.5 h-3.5" />
              Works with your AI assistant
            </div>
            <h2
              data-ai
              className="font-display font-bold tracking-tight text-3xl sm:text-4xl text-slate-50 mb-4"
            >
              Ask your AI about your money
            </h2>
            <p data-ai className="text-lg text-slate-400 mb-8">
              nilu. runs an MCP server, so Claude and other assistants can answer questions from your real
              finances instead of guesses.
            </p>
            <ul className="space-y-5 mb-8">
              {POINTS.map(({ icon: Icon, title, body }) => (
                <li key={title} data-ai className="flex gap-3">
                  <span className="w-9 h-9 shrink-0 rounded-xl bg-accent/15 border border-accent/20 flex items-center justify-center">
                    <Icon className="w-4 h-4 text-accent" />
                  </span>
                  <span className="min-w-0">
                    <span className="block font-display font-semibold text-sm text-slate-100">{title}</span>
                    <span className="block text-sm text-slate-400 leading-relaxed">{body}</span>
                  </span>
                </li>
              ))}
            </ul>
            <ConnectBox />
          </div>
          <ChatPreview />
        </div>
      </div>
    </div>
  )
}

import { useState, type ReactNode } from 'react'
import { Check, Copy } from 'lucide-react'
import type { ServiceState } from '../lib/types'

/* The shared component vocabulary. Content sits on solid panels;
   glass is reserved for chrome (sidebar, palette, overlays). */

export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`panel ${className}`}>{children}</div>
}

export function PanelHead({ label, right }: { label: string; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between px-5 pt-4 pb-3">
      <span className="label-mono">{label}</span>
      {right}
    </div>
  )
}

const stateColor: Record<string, string> = {
  running: 'var(--color-run)', ok: 'var(--color-run)', completed: 'var(--color-run)',
  confident: 'var(--color-run)', done: 'var(--color-run)',
  pending: 'var(--color-pend)', waiting_approval: 'var(--color-pend)', gated: 'var(--color-pend)',
  degraded: 'var(--color-pend)', review: 'var(--color-pend)', scheduled: 'var(--color-pend)',
  medium: 'var(--color-pend)', needs_you: 'var(--color-pend)',
  failed: 'var(--color-fail)', offline: 'var(--color-fail)', blocked: 'var(--color-fail)',
  high: 'var(--color-fail)', interrupted: 'var(--color-fail)',
}

export function StatusDot({ state, live = false }: { state: string; live?: boolean }) {
  const color = stateColor[state] ?? 'var(--color-low)'
  return (
    <span
      aria-label={state}
      className="inline-block size-1.5 shrink-0 rounded-full"
      style={{
        background: color,
        animation: live ? 'dot-pulse 2.4s ease-out infinite' : undefined,
        ['--pulse-color' as string]: `color-mix(in oklch, ${color} 45%, transparent)`,
      }}
    />
  )
}

export function Pill({ children, tone }: { children: ReactNode; tone?: string }) {
  const color = tone ? stateColor[tone] : undefined
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-line px-2 py-0.5 font-mono text-[11px] text-mid"
      style={color ? { color, borderColor: 'color-mix(in oklch, ' + color + ' 30%, transparent)' } : undefined}
    >
      {children}
    </span>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded-[5px] border border-line bg-raise2 px-1.5 py-px font-mono text-[11px] text-low">
      {children}
    </kbd>
  )
}

export function Btn({
  children, onClick, kind = 'quiet', disabled, className = '',
}: {
  children: ReactNode; onClick?: () => void; kind?: 'quiet' | 'primary' | 'danger'
  disabled?: boolean; className?: string
}) {
  const styles = {
    quiet: 'text-mid hover:text-hi hover:bg-ink/5',
    primary: 'bg-ink/8 text-hi hover:bg-ink/12',
    danger: 'text-fail hover:bg-fail/10',
  }[kind]
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors duration-150 disabled:pointer-events-none disabled:opacity-40 ${styles} ${className}`}
    >
      {children}
    </button>
  )
}

export function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${Math.floor(s)}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

export function Mono({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono text-[12px] ${className}`}>{children}</span>
}

// data you can lift straight off the instrument panel; the tick is the feedback
export function Copyable({ text, children, className = '' }: {
  text: string; children: ReactNode; className?: string
}) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      title="Copy"
      onClick={(e) => {
        e.stopPropagation()
        void navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1200)
      }}
      className={`group/copy inline-flex min-w-0 items-center gap-1.5 text-left ${className}`}
    >
      {children}
      {copied ? (
        <Check size={11} className="shrink-0 text-run" />
      ) : (
        <Copy size={11} className="shrink-0 text-low opacity-0 transition-opacity group-hover/copy:opacity-60" />
      )}
    </button>
  )
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 py-14 text-center">
      <p className="text-[13px] text-mid">{title}</p>
      {hint && <p className="text-[12px] text-low">{hint}</p>}
    </div>
  )
}

export function ServiceRow({ name, state }: { name: string; state: ServiceState }) {
  return (
    <div className="flex items-center justify-between py-1">
      <Mono className="text-mid">{name}</Mono>
      <span className="flex items-center gap-2">
        <StatusDot state={state} live={state !== 'ok'} />
        <Mono className="text-low">{state}</Mono>
      </span>
    </div>
  )
}

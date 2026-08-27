// One-time "what's new" modal, shown after an in-app update relaunches on a
// newer version. Mirrors the Tour's scrim + glass-strong card idiom and its
// once-only localStorage gate (WHATS_NEW_KEY). Silent on a fresh install — the
// Tour owns first-run — and records the baseline version so it can't fire late.
import { useEffect, useState } from 'react'
import { Btn } from './ui'
import { CHANGELOG, WHATS_NEW_KEY, shouldShowWhatsNew, type WhatsNewEntry } from '../lib/whatsNew'

export function WhatsNew() {
  const [entry, setEntry] = useState<WhatsNewEntry | null>(null)
  const [version, setVersion] = useState('')

  useEffect(() => {
    let cancelled = false
    void fetch('/api/meta')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled || !d?.version) return
        const current: string = d.version
        let seen: string | null = null
        try {
          seen = localStorage.getItem(WHATS_NEW_KEY)
        } catch {
          seen = null
        }
        if (shouldShowWhatsNew(current, seen)) {
          setVersion(current)
          setEntry(CHANGELOG[current])
        } else if (!seen) {
          // Fresh install: record the baseline so the next update — not this
          // one — is the first time the modal appears.
          try {
            localStorage.setItem(WHATS_NEW_KEY, current)
          } catch {
            /* private mode / storage blocked — harmless, just re-checks next launch */
          }
        }
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const dismiss = () => {
    try {
      localStorage.setItem(WHATS_NEW_KEY, version)
    } catch {
      /* storage blocked — modal may reappear next launch, acceptable */
    }
    setEntry(null)
  }

  if (!entry) return null

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="What's new"
    >
      <div className="absolute inset-0 bg-black/52" onClick={dismiss} />
      <div
        className="glass-strong relative w-full max-w-[420px] rounded-[16px] p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <p className="label-mono mb-1.5">updated to v{version}</p>
        <h2 className="mb-3 text-[17px] font-semibold tracking-[-0.01em]">{entry.title}</h2>
        <ul className="mb-5 flex flex-col gap-2.5">
          {entry.items.map((it, n) => (
            <li key={n} className="flex gap-2 text-[13px] leading-relaxed text-mid">
              <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-acc" />
              <span>{it}</span>
            </li>
          ))}
        </ul>
        <div className="flex justify-end">
          <Btn onClick={dismiss}>Got it</Btn>
        </div>
      </div>
    </div>
  )
}

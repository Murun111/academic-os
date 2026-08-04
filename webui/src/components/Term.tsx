import { useEffect, useRef, useState, type ReactNode } from 'react'
import { GUIDANCE } from '../lib/guidance'

/* Inline glossary term. Click/Enter opens a small factual popover so a
   first-gen student never has to leave the page to look up jargon. */

export function Term({ k, children }: { k: string; children: ReactNode }) {
  const entry = GUIDANCE[k]
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const onClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onClick)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onClick)
    }
  }, [open])

  if (!entry) return <>{children}</>

  return (
    <span ref={wrapRef} className="relative inline">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); setOpen((o) => !o) } }}
        aria-expanded={open}
        className="border-b border-dotted border-current bg-transparent p-0 text-inherit"
      >
        {children}
      </button>
      {open && (
        <span
          role="dialog"
          className="panel absolute left-0 top-full z-40 mt-1.5 block w-max max-w-[320px] p-3 text-left"
        >
          <span className="mb-1 block text-[13px] font-medium text-hi">{entry.title}</span>
          <span className="block text-[12.5px] leading-relaxed text-mid">{entry.body}</span>
        </span>
      )}
    </span>
  )
}

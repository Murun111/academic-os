import { useMemo, useState } from 'react'
import { useOs } from '../lib/store'
import { guidanceForStage } from '../lib/guidance'
import { Panel, PanelHead, Mono } from './ui'

/* Stage-aware glossary panel. Dashboard gets the full version; Study gets a
   collapsed toggle so it doesn't compete with the day's tasks. */

export function GuidePanel({ compact = false }: { compact?: boolean }) {
  const { stage } = useOs()
  const entries = useMemo(() => guidanceForStage(stage), [stage])
  const [open, setOpen] = useState(!compact)
  const [filter, setFilter] = useState('')
  const [expandedKey, setExpandedKey] = useState<string | null>(null)

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (compact || !q) return entries
    return entries.filter(([, e]) => e.title.toLowerCase().includes(q) || e.body.toLowerCase().includes(q))
  }, [entries, filter, compact])

  if (compact && !open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="w-full rounded-[10px] border border-line px-3 py-2 text-left text-[12.5px] text-mid hover:bg-black/4"
      >
        New to this? Open the guide
      </button>
    )
  }

  return (
    <Panel>
      <PanelHead label="guide" right={<Mono className="text-low">{filtered.length}</Mono>} />
      {!compact && (
        <div className="px-5 pb-2">
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter terms…"
            className="w-full rounded-md border border-line bg-transparent px-2 py-1 text-[12.5px] text-hi placeholder:text-low focus:outline-none"
          />
        </div>
      )}
      <div className="flex flex-col gap-px px-2 pb-3">
        {filtered.map(([key, entry]) => {
          const isOpen = expandedKey === key
          return (
            <div key={key} className="rounded-[10px] px-3 py-2 hover:bg-black/4">
              <button
                type="button"
                onClick={() => setExpandedKey(isOpen ? null : key)}
                aria-expanded={isOpen}
                className="w-full text-left text-[13px] text-hi"
              >
                {entry.title}
              </button>
              {isOpen && <p className="mt-1 text-[12.5px] leading-relaxed text-mid">{entry.body}</p>}
            </div>
          )
        })}
        {filtered.length === 0 && (
          <p className="px-3 py-4 text-center text-[12.5px] text-low">No matching terms.</p>
        )}
      </div>
    </Panel>
  )
}

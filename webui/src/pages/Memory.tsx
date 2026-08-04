import { useEffect, useState } from 'react'
import { Search } from 'lucide-react'
import { api } from '../lib/api'
import type { MemoryEntry, MemoryKind, MemoryStats } from '../lib/types'
import { EmptyState, Mono, Panel, PanelHead, Pill, timeAgo } from '../components/ui'
import { Spark, SplitBar } from '../components/charts'

const KINDS: Array<MemoryKind | 'all'> = ['all', 'fact', 'preference', 'trajectory', 'entity']

// monochrome shades per kind — distribution, not status, so no color
const KIND_SHADE: Record<MemoryKind, string> = {
  fact: 'oklch(1 0 0 / 60%)',
  trajectory: 'oklch(1 0 0 / 45%)',
  preference: 'oklch(1 0 0 / 32%)',
  entity: 'oklch(1 0 0 / 20%)',
}

export function Memory() {
  const [entries, setEntries] = useState<MemoryEntry[]>([])
  const [stats, setStats] = useState<MemoryStats | null>(null)
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState<MemoryKind | 'all'>('all')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    void api.memoryStats().then(setStats)
  }, [])

  useEffect(() => {
    const t = setTimeout(() => {
      setLoading(true)
      void api.memories(query || undefined).then((m) => {
        setEntries(m)
        setLoading(false)
      })
    }, 180)
    return () => clearTimeout(t)
  }, [query])

  const visible = entries.filter((e) => kind === 'all' || e.kind === kind)

  return (
    <div className="mx-auto max-w-[820px]">
      <div className="mb-6">
        <p className="label-mono mb-1">index · recall · compact · trajectory</p>
        <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Memory</h1>
      </div>

      {stats && (
        <Panel className="mb-5">
          <PanelHead
            label="spine growth · 30d"
            right={
              <Mono className="text-low">
                {stats.growth[stats.growth.length - 1]} entries
              </Mono>
            }
          />
          <div className="px-5 pb-4">
            <Spark values={stats.growth} height={44} showLast />
            <div className="mt-3">
              <SplitBar
                parts={(Object.entries(stats.byKind) as Array<[MemoryKind, number]>).map(([k, v]) => ({
                  label: k,
                  value: v,
                  color: KIND_SHADE[k],
                }))}
              />
            </div>
          </div>
        </Panel>
      )}

      <div className="mb-4 flex items-center gap-3">
        <div className="panel flex flex-1 items-center gap-2.5 px-3.5 py-2">
          <Search size={14} className="text-low" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search what the OS knows…"
            className="flex-1 bg-transparent text-[13.5px] text-hi outline-none placeholder:text-low"
          />
        </div>
        <div className="flex gap-1">
          {KINDS.map((k) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              className={`rounded-full px-3 py-1 font-mono text-[11.5px] transition-colors duration-150 ${
                kind === k ? 'bg-black/8 text-hi' : 'text-low hover:text-mid'
              }`}
            >
              {k}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => <div key={i} className="panel h-[72px] animate-pulse" />)}
        </div>
      ) : visible.length === 0 ? (
        <div className="panel">
          <EmptyState title="No memories match." hint="The spine grows as you chat and agents run." />
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {visible.map((m) => (
            <div key={m.id} className="panel group px-5 py-3.5">
              <div className="mb-1.5 flex items-center gap-2.5">
                <Pill>{m.kind}</Pill>
                <Mono className="text-low">{m.source}</Mono>
                <Mono className="ml-auto text-low">{timeAgo(m.t)} ago</Mono>
              </div>
              <p className="mb-2 max-w-[70ch] text-[13.5px] leading-relaxed text-mid group-hover:text-hi">
                {m.text}
              </p>
              {/* strength: a hairline, not a gauge */}
              <div className="flex items-center gap-2">
                <div className="h-px w-[120px] overflow-hidden bg-black/6">
                  <div className="h-full bg-black/40" style={{ width: `${m.strength * 100}%` }} />
                </div>
                <Mono className="text-[10.5px] text-low">{m.strength.toFixed(2)}</Mono>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

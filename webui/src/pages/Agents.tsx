import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Copy, Play, X } from 'lucide-react'
import { useOs } from '../lib/store'
import { api } from '../lib/api'
import { Btn, Mono, Pill, StatusDot, timeAgo } from '../components/ui'
import { MiniBars, SplitBar } from '../components/charts'
import { ContextMenu, useContextMenu } from '../components/ContextMenu'
import type { AgentInfo, AgentStats } from '../lib/types'

export function Agents() {
  const { agents, runs, runAgent } = useOs()
  const [selected, setSelected] = useState<string | null>(null)
  const { menu, openMenu, closeMenu } = useContextMenu()
  const drawerRef = useRef<HTMLElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const [stats, setStats] = useState<AgentStats | null>(null)
  const agent = agents.find((a) => a.name === selected) ?? null
  const agentRuns = runs.filter((r) => r.agent === selected)

  useEffect(() => {
    setStats(null)
    if (selected) void api.agentStats(selected).then(setStats)
  }, [selected])

  useEffect(() => {
    if (!selected) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setSelected(null) }
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      // row clicks handle their own toggle; everything else outside the drawer closes it
      if (drawerRef.current?.contains(t) || listRef.current?.contains(t)) return
      setSelected(null)
    }
    window.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [selected])

  const agentMenu = (a: AgentInfo) => [
    { label: 'Run now', icon: Play, onSelect: () => void runAgent(a.name) },
    { label: 'Copy name', icon: Copy, onSelect: () => void navigator.clipboard.writeText(a.name) },
  ]

  return (
    <div className="mx-auto max-w-[1200px]">
      <div className="mb-6">
        <p className="label-mono mb-1">helpers that work in the background</p>
        <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Assistants</h1>
      </div>

      <div ref={listRef} className="flex flex-col gap-2">
        {agents.map((a) => (
          <button
            key={a.name}
            onClick={() => setSelected(a.name === selected ? null : a.name)}
            onContextMenu={(e) => openMenu(e, agentMenu(a))}
            className={`panel flex items-center gap-4 px-5 py-3.5 text-left transition-colors duration-150 hover:bg-raise2 ${
              selected === a.name ? 'border-black/15' : ''
            }`}
          >
            <StatusDot state={a.state} live={a.state === 'running'} />
            <div className="w-[160px] shrink-0">
              <Mono className="text-hi">{a.name}</Mono>
            </div>
            <p className="flex-1 truncate text-[13px] text-mid">
              {a.state === 'running' && a.currentTask ? a.currentTask : a.description}
            </p>
            <Pill tone={a.autonomy === 'auto' ? 'running' : a.autonomy === 'gated' ? 'pending' : undefined}>
              {a.autonomy}
            </Pill>
            <Mono className="w-[70px] text-right text-low">
              {a.lastRun ? `${timeAgo(a.lastRun)} ago` : 'never'}
            </Mono>
          </button>
        ))}
      </div>

      {/* detail: floating glass panel, the one overlay glass earns */}
      <AnimatePresence>
        {agent && (
          <motion.aside
            ref={drawerRef}
            className="glass-strong fixed top-4 right-4 bottom-4 z-30 flex w-[400px] flex-col rounded-[18px] p-6"
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 16 }}
            transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="mb-1 flex items-start justify-between">
              <div className="flex items-center gap-2.5">
                <StatusDot state={agent.state} live={agent.state === 'running'} />
                <h2 className="font-mono text-[15px] text-hi">{agent.name}</h2>
              </div>
              <button onClick={() => setSelected(null)} className="text-low hover:text-mid">
                <X size={16} />
              </button>
            </div>
            <p className="mb-5 text-[13px] leading-relaxed text-mid">{agent.description}</p>

            <div className="mb-5 grid grid-cols-3 gap-3">
              {[
                ['state', agent.state],
                ['autonomy', agent.autonomy],
                ['runs today', String(agent.runsToday)],
              ].map(([k, v]) => (
                <div key={k}>
                  <p className="label-mono mb-0.5">{k}</p>
                  <Mono className="text-hi">{v}</Mono>
                </div>
              ))}
            </div>

            <p className="label-mono mb-2">tools</p>
            <div className="mb-5 flex flex-wrap gap-1.5">
              {agent.tools.map((t) => <Pill key={t}>{t}</Pill>)}
            </div>

            {stats && (
              <div className="mb-5">
                <div className="mb-1.5 flex items-baseline justify-between">
                  <p className="label-mono">runs · 7d</p>
                  <Mono className="text-[10.5px] text-low">
                    {stats.runsByDay.reduce((a, b) => a + b, 0)} total
                  </Mono>
                </div>
                <MiniBars values={stats.runsByDay} height={30} />
                <div className="mt-3">
                  <SplitBar
                    parts={[
                      { label: 'completed', value: stats.completed, color: 'var(--color-run)' },
                      { label: 'failed', value: stats.failed, color: 'var(--color-fail)' },
                    ]}
                  />
                </div>
              </div>
            )}

            <p className="label-mono mb-2">recent runs</p>
            <div className="flex-1 overflow-y-auto">
              {agentRuns.length === 0 && <p className="text-[12.5px] text-low">No runs in this session.</p>}
              {agentRuns.map((r) => (
                <div key={r.id} className="mb-2 rounded-[10px] border border-hairline px-3 py-2.5">
                  <div className="mb-1 flex items-center gap-2">
                    <StatusDot state={r.status} live={r.status === 'running'} />
                    <Mono className="text-low">{timeAgo(r.startedAt)} ago</Mono>
                    {r.tokens && <Mono className="ml-auto text-low">{(r.tokens / 1000).toFixed(1)}k tok</Mono>}
                  </div>
                  <p className="text-[12.5px] leading-snug text-mid">{r.goal}</p>
                </div>
              ))}
            </div>

            <Btn
              kind="primary"
              className="mt-4 flex items-center justify-center gap-2"
              disabled={agent.state === 'running'}
              onClick={() => void runAgent(agent.name)}
            >
              <Play size={13} /> {agent.state === 'running' ? 'Running…' : 'Run now'}
            </Btn>
          </motion.aside>
        )}
      </AnimatePresence>

      <ContextMenu menu={menu} onClose={closeMenu} />
    </div>
  )
}

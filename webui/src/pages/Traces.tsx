import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Wrench, Sparkles, ShieldAlert, Scale, FileCheck, Copy, Bot } from 'lucide-react'
import { useOs } from '../lib/store'
import { Copyable, EmptyState, Mono, Panel, PanelHead, Pill, StatusDot, timeAgo } from '../components/ui'
import { StepTimeline } from '../components/charts'
import { ContextMenu, useContextMenu } from '../components/ContextMenu'
import type { Run, TraceStep } from '../lib/types'

const STEP_ICON: Record<TraceStep['kind'], typeof Wrench> = {
  tool: Wrench,
  llm: Sparkles,
  critic: Scale,
  gate: ShieldAlert,
  result: FileCheck,
}

export function Traces() {
  const runs = useOs((s) => s.runs)
  const [selectedId, setSelectedId] = useState<string | null>(runs[0]?.id ?? null)
  const run = runs.find((r) => r.id === selectedId) ?? runs[0] ?? null
  const navigate = useNavigate()
  const { menu, openMenu, closeMenu } = useContextMenu()

  const runMenu = (r: Run) => [
    { label: 'Copy goal', icon: Copy, onSelect: () => void navigator.clipboard.writeText(r.goal) },
    { label: 'Copy run id', icon: Copy, onSelect: () => void navigator.clipboard.writeText(r.id) },
    { label: 'Go to agent', icon: Bot, onSelect: () => navigate('/agents') },
  ]

  return (
    <div className="mx-auto max-w-[1100px]">
      <div className="mb-6">
        <p className="label-mono mb-1">trajectories · verify before commit</p>
        <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Traces</h1>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[360px_1fr]">
        <div className="flex flex-col gap-2">
          {runs.map((r) => (
            <button
              key={r.id}
              onClick={() => setSelectedId(r.id)}
              onContextMenu={(e) => openMenu(e, runMenu(r))}
              className={`panel px-4 py-3 text-left transition-colors duration-150 hover:bg-raise2 ${
                run?.id === r.id ? 'border-black/15' : ''
              }`}
            >
              <div className="mb-1 flex items-center gap-2">
                <StatusDot state={r.status} live={r.status === 'running'} />
                <Mono className="text-hi">{r.agent}</Mono>
                <Mono className="ml-auto text-low">{timeAgo(r.startedAt)} ago</Mono>
              </div>
              <p className="truncate text-[12.5px] text-mid">{r.goal}</p>
            </button>
          ))}
          {runs.length === 0 && (
            <div className="panel"><EmptyState title="No runs recorded yet." /></div>
          )}
        </div>

        {run && (
          <Panel className="h-fit">
            <PanelHead
              label={`run · ${run.agent}`}
              right={
                <span className="flex items-center gap-3">
                  {run.tokens && <Mono className="text-low">{(run.tokens / 1000).toFixed(1)}k tok</Mono>}
                  {run.elapsedMs && <Mono className="text-low">{(run.elapsedMs / 1000).toFixed(0)}s</Mono>}
                  <Pill tone={run.status}>{run.status.replace('_', ' ')}</Pill>
                </span>
              }
            />
            <div className="px-5 pb-2">
              <p className="mb-4 max-w-[60ch] text-[14px] leading-relaxed text-hi">{run.goal}</p>

              <StepTimeline steps={run.steps} />

              {/* trajectory: a spine with steps hanging off it */}
              <div className="relative ml-2 border-l border-hairline pb-3 pl-6">
                {run.steps.map((s, i) => {
                  const Icon = STEP_ICON[s.kind]
                  return (
                    <div key={i} className="relative mb-5 last:mb-0">
                      <span
                        className={`absolute top-0.5 -left-[31px] grid size-[22px] place-items-center rounded-full border bg-raise ${
                          s.ok ? 'border-line text-mid' : 'border-fail/40 text-fail'
                        }`}
                      >
                        <Icon size={11} strokeWidth={1.75} />
                      </span>
                      <div className="flex items-baseline gap-2.5">
                        <Mono className={s.ok ? 'text-hi' : 'text-fail'}>{s.label}</Mono>
                        <Mono className="text-[10.5px] text-low">{s.kind}</Mono>
                        <Mono className="ml-auto text-low">
                          {new Date(s.t).toLocaleTimeString('en-US', { hour12: false })}
                        </Mono>
                      </div>
                      {s.detail && (
                        <Copyable text={s.detail} className="mt-0.5">
                          <p className="max-w-[56ch] text-[12.5px] leading-snug text-mid">{s.detail}</p>
                        </Copyable>
                      )}
                    </div>
                  )
                })}
                {run.status === 'running' && (
                  <div className="relative">
                    <span className="absolute top-1 -left-[27.5px] size-3.5 rounded-full border border-line bg-raise">
                      <span className="absolute inset-[3px] rounded-full bg-run" style={{ animation: 'dot-pulse 2.4s ease-out infinite' }} />
                    </span>
                    <Mono className="text-low">in flight…</Mono>
                  </div>
                )}
              </div>
            </div>
          </Panel>
        )}
      </div>

      <ContextMenu menu={menu} onClose={closeMenu} />
    </div>
  )
}

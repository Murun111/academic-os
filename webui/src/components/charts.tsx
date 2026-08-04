import type { TraceStep } from '../lib/types'
import { Mono } from './ui'

/* Hand-rolled SVG micro-charts. Monochrome by default; status colors only
   where the data means something (gates amber, failures red). No grids,
   no legends unless the reading is ambiguous, mono-font labels only. */

export function Spark({
  values, height = 36, showLast = false, className = '',
}: {
  values: number[]; height?: number; showLast?: boolean; className?: string
}) {
  if (values.length < 2) return null
  const w = 100
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const pts = values.map((v, i) => [
    (i / (values.length - 1)) * w,
    height - 3 - ((v - min) / span) * (height - 8),
  ])
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area = `0,${height} ${line} ${w},${height}`
  const [lx, ly] = pts[pts.length - 1]
  return (
    <svg
      viewBox={`0 0 ${w} ${height}`}
      preserveAspectRatio="none"
      className={`block w-full ${className}`}
      style={{ height }}
      aria-hidden
    >
      <polygon points={area} fill="oklch(0 0 0 / 6%)" />
      <polyline
        points={line}
        fill="none"
        stroke="oklch(0 0 0 / 55%)"
        strokeWidth="1.2"
        vectorEffect="non-scaling-stroke"
        strokeLinejoin="round"
      />
      {showLast && <circle cx={lx} cy={ly} r="2" fill="var(--color-run)" vectorEffect="non-scaling-stroke" />}
    </svg>
  )
}

export function MiniBars({
  values, height = 28, highlightLast = true,
}: {
  values: number[]; height?: number; highlightLast?: boolean
}) {
  const max = Math.max(...values, 1)
  return (
    <div className="flex items-end gap-px" style={{ height }} aria-hidden>
      {values.map((v, i) => (
        <div
          key={i}
          className="flex-1 rounded-[1px]"
          style={{
            height: `${Math.max(4, (v / max) * 100)}%`,
            background:
              highlightLast && i === values.length - 1
                ? 'oklch(0 0 0 / 55%)'
                : 'oklch(0 0 0 / 18%)',
          }}
        />
      ))}
    </div>
  )
}

export function SplitBar({
  parts,
}: {
  parts: Array<{ value: number; color: string; label: string }>
}) {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1
  return (
    <div>
      <div className="flex h-1 overflow-hidden rounded-full">
        {parts.map((p) => (
          <div key={p.label} style={{ width: `${(p.value / total) * 100}%`, background: p.color }} />
        ))}
      </div>
      <div className="mt-1.5 flex gap-4">
        {parts.map((p) => (
          <span key={p.label} className="flex items-center gap-1.5">
            <span className="size-1.5 rounded-full" style={{ background: p.color }} />
            <Mono className="text-[10.5px] text-low">{p.label} {p.value}</Mono>
          </span>
        ))}
      </div>
    </div>
  )
}

/* where a run spent its time: one horizontal band, segments by step kind */

const KIND_SHADE: Record<TraceStep['kind'], string> = {
  tool: 'oklch(1 0 0 / 30%)',
  llm: 'oklch(1 0 0 / 55%)',
  critic: 'oklch(1 0 0 / 42%)',
  gate: 'color-mix(in oklch, var(--color-pend) 70%, transparent)',
  result: 'oklch(1 0 0 / 18%)',
}

export function StepTimeline({ steps }: { steps: TraceStep[] }) {
  const withDur = steps.filter((s) => (s.durMs ?? 0) > 0)
  if (withDur.length < 2) return null
  const total = withDur.reduce((s, x) => s + (x.durMs ?? 0), 0)
  return (
    <div className="mb-5">
      <div className="flex h-[10px] gap-px overflow-hidden rounded-[3px]">
        {withDur.map((s, i) => (
          <div
            key={i}
            title={`${s.label} · ${((s.durMs ?? 0) / 1000).toFixed(1)}s`}
            style={{
              width: `${((s.durMs ?? 0) / total) * 100}%`,
              background: s.ok ? KIND_SHADE[s.kind] : 'color-mix(in oklch, var(--color-fail) 70%, transparent)',
            }}
          />
        ))}
      </div>
      <div className="mt-1.5 flex justify-between">
        <Mono className="text-[10.5px] text-low">tool · llm · critic{withDur.some((s) => s.kind === 'gate') ? ' · gate' : ''}</Mono>
        <Mono className="text-[10.5px] text-low">{(total / 1000).toFixed(0)}s total</Mono>
      </div>
    </div>
  )
}

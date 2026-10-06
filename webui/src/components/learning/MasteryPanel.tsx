import { useCallback, useEffect, useMemo, useState } from 'react'
import { Plus } from 'lucide-react'
import {
  learning,
  isLearningApiError,
  isUnavailable,
  MASTERY_STATUSES,
  type MasteryMatrix,
  type MasteryStatus,
  type MasteryTopic,
} from '../../lib/learningApi'
import { Btn, EmptyState, Mono, Panel, PanelHead } from '../ui'

const STATUS_LABEL: Record<MasteryStatus, string> = {
  needs_review: 'Needs review',
  developing: 'Developing',
  proficient: 'Proficient',
  mastered: 'Mastered',
}

// bar fill per status: 25 / 50 / 75 / 100 percent
const STATUS_LEVEL: Record<MasteryStatus, number> = {
  needs_review: 25,
  developing: 50,
  proficient: 75,
  mastered: 100,
}

const STATUS_COLOR: Record<MasteryStatus, string> = {
  needs_review: 'var(--color-fail)',
  developing: 'var(--color-pend)',
  proficient: 'var(--color-acc)',
  mastered: 'var(--color-run)',
}

function errorMessage(e: unknown, what: string): string {
  if (isUnavailable(e)) return `The learning service is unreachable right now. ${what} will work once it is back.`
  if (isLearningApiError(e) && e.status === 404) return 'That topic no longer exists. Refresh to see the current list.'
  if (isLearningApiError(e) && e.status === 422) return `Invalid input: ${e.detail}`
  return `Could not ${what.toLowerCase()}. Try again.`
}

function accuracy(t: MasteryTopic): string {
  if (t.attempts_count <= 0) return 'no attempts'
  return `${Math.round((t.correct_count / t.attempts_count) * 100)}% of ${t.attempts_count}`
}

function MasteryBar({ status, label }: { status: MasteryStatus; label: string }) {
  const pct = STATUS_LEVEL[status] ?? 0
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      aria-valuetext={STATUS_LABEL[status]}
      className="h-1.5 w-full overflow-hidden rounded-full bg-ink/8"
    >
      <div
        className="h-full rounded-full transition-[width] duration-300"
        style={{ width: `${pct}%`, background: STATUS_COLOR[status] }}
      />
    </div>
  )
}

function TopicRow({
  topic,
  busy,
  onChange,
}: {
  topic: MasteryTopic
  busy: boolean
  onChange: (id: string, status: MasteryStatus) => void
}) {
  return (
    <li className="flex flex-col gap-2 rounded-[10px] px-3 py-2.5 hover:bg-ink/4 sm:flex-row sm:items-center sm:gap-4">
      <div className="min-w-0 sm:w-[220px] sm:shrink-0">
        <p className="truncate text-[13px] text-hi">{topic.name}</p>
        <Mono className="text-low">{topic.course_name || 'General'} · {accuracy(topic)}</Mono>
      </div>
      <div className="flex-1">
        <MasteryBar status={topic.status} label={`${topic.name} mastery`} />
      </div>
      <select
        value={topic.status}
        disabled={busy}
        onChange={(e) => onChange(topic.id, e.target.value as MasteryStatus)}
        aria-label={`Mastery level for ${topic.name}`}
        className="rounded-md border border-line bg-transparent px-2 py-1 font-mono text-[12px] text-mid focus:outline-none focus-visible:ring-1 focus-visible:ring-ink/30 disabled:opacity-40"
      >
        {MASTERY_STATUSES.map((s) => (
          <option key={s} value={s}>{STATUS_LABEL[s]}</option>
        ))}
      </select>
    </li>
  )
}

export function MasteryPanel() {
  const [matrix, setMatrix] = useState<MasteryMatrix | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const [name, setName] = useState('')
  const [course, setCourse] = useState('')
  const [status, setStatus] = useState<MasteryStatus>('developing')
  const [adding, setAdding] = useState(false)

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      setMatrix(await learning.mastery())
    } catch (e) {
      setLoadError(errorMessage(e, 'Load mastery'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const topics = useMemo(
    () => [...(matrix?.topics ?? [])].sort(
      (a, b) => STATUS_LEVEL[a.status] - STATUS_LEVEL[b.status] || a.name.localeCompare(b.name),
    ),
    [matrix],
  )

  const handleAdd = async () => {
    const n = name.trim()
    if (!n || adding) return
    setAdding(true)
    setActionError(null)
    try {
      const c = course.trim()
      await learning.addTopic({ name: n, course_name: c || null, status })
      setName('')
      setCourse('')
      setStatus('developing')
      await load()
    } catch (e) {
      setActionError(errorMessage(e, 'Add topic'))
    } finally {
      setAdding(false)
    }
  }

  const handleStatus = async (id: string, next: MasteryStatus) => {
    setBusyId(id)
    setActionError(null)
    try {
      const updated = await learning.setTopicStatus(id, next)
      setMatrix((m) => (m ? { ...m, topics: m.topics.map((t) => (t.id === id ? updated : t)) } : m))
      void load() // refresh overall_mastery
    } catch (e) {
      setActionError(errorMessage(e, 'Update topic'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Panel>
        <PanelHead
          label="mastery overview"
          right={
            matrix && topics.length > 0 ? (
              <Mono className="text-mid">overall {Math.round(matrix.overall_mastery)}%</Mono>
            ) : undefined
          }
        />
        <div className="px-3 pb-4">
          {loading ? (
            <p className="px-3 py-8 text-center text-[13px] text-low" role="status">Loading mastery…</p>
          ) : loadError ? (
            <div className="flex flex-col items-center gap-2 px-3 py-10 text-center" role="alert">
              <p className="text-[13px] text-mid">{loadError}</p>
              <Btn onClick={() => { setLoading(true); void load() }}>Retry</Btn>
            </div>
          ) : topics.length === 0 ? (
            <EmptyState title="No topics yet" hint="Add a topic below, or submit a quiz and its concepts appear here." />
          ) : (
            <>
              <ul className="flex flex-col">
                {topics.map((t) => (
                  <TopicRow key={t.id} topic={t} busy={busyId === t.id} onChange={(id, s) => void handleStatus(id, s)} />
                ))}
              </ul>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 px-3" aria-hidden="true">
                {MASTERY_STATUSES.map((s) => (
                  <span key={s} className="flex items-center gap-1.5">
                    <span className="inline-block size-1.5 rounded-full" style={{ background: STATUS_COLOR[s] }} />
                    <Mono className="text-low">{STATUS_LABEL[s]}</Mono>
                  </span>
                ))}
              </div>
            </>
          )}
          {actionError && (
            <p className="mt-3 px-3 text-[12px] text-fail" role="alert">{actionError}</p>
          )}
        </div>
      </Panel>

      <Panel>
        <form
          className="flex flex-wrap items-center gap-2 px-4 py-3"
          onSubmit={(e) => { e.preventDefault(); void handleAdd() }}
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="New topic…"
            aria-label="Topic name"
            className="min-w-[160px] flex-1 bg-transparent text-[13px] text-hi placeholder:text-low focus:outline-none"
          />
          <input
            value={course}
            onChange={(e) => setCourse(e.target.value)}
            placeholder="Course (optional)"
            aria-label="Course name"
            className="w-[160px] rounded-md border border-line bg-transparent px-2 py-1 text-[12px] text-mid placeholder:text-low focus:outline-none"
          />
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as MasteryStatus)}
            aria-label="Starting mastery level"
            className="rounded-md border border-line bg-transparent px-2 py-1 font-mono text-[12px] text-mid focus:outline-none"
          >
            {MASTERY_STATUSES.map((s) => (
              <option key={s} value={s}>{STATUS_LABEL[s]}</option>
            ))}
          </select>
          <button
            type="submit"
            disabled={adding || !name.trim()}
            className="flex items-center gap-1.5 rounded-lg bg-ink/8 px-3 py-1.5 text-[13px] font-medium text-hi transition-colors duration-150 hover:bg-ink/12 disabled:pointer-events-none disabled:opacity-40"
          >
            <Plus size={13} aria-hidden="true" /> Add topic
          </button>
        </form>
      </Panel>
    </div>
  )
}

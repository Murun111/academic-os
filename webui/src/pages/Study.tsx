import { useCallback, useEffect, useMemo, useState } from 'react'
import { Plus } from 'lucide-react'
import { study, kindTone, isOverdue, isToday, type Agenda, type AgendaItem } from '../lib/studyApi'
import { Btn, EmptyState, Mono, Panel, PanelHead, Pill } from '../components/ui'
import { GuidePanel } from '../components/GuidePanel'

const WEEK_DAYS = 7

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00`)
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}

function dayLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

function KindPill({ kind }: { kind: AgendaItem['kind'] }) {
  return <Pill tone={kindTone(kind)}>{kind}</Pill>
}

function AgendaRow({ item, onToggleDone }: { item: AgendaItem; onToggleDone?: (id: string) => void }) {
  const isTask = item.kind === 'task'
  return (
    <div className="flex items-center gap-3 rounded-[10px] px-3 py-2 hover:bg-black/4">
      {isTask && item.id ? (
        <input
          type="checkbox"
          checked={false}
          onChange={() => onToggleDone?.(item.id as string)}
          className="size-3.5 accent-black/70"
          aria-label={`Mark "${item.title ?? 'task'}" done`}
        />
      ) : (
        <span className="inline-block size-3.5" />
      )}
      <KindPill kind={item.kind} />
      <span className="flex-1 truncate text-[13px] text-mid">{item.title ?? '(untitled)'}</span>
      {item.date && isOverdue(item.date) && <Mono className="text-fail">overdue</Mono>}
      <Mono className="w-[76px] shrink-0 text-right text-low">{item.date ?? '—'}</Mono>
    </div>
  )
}

export function Study() {
  const [agenda, setAgenda] = useState<Agenda>({ items: [], count: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [title, setTitle] = useState('')
  const [day, setDay] = useState(todayIso())
  const [adding, setAdding] = useState(false)

  const load = useCallback(async () => {
    setError(false)
    try {
      const a = await study.agenda(WEEK_DAYS)
      setAgenda(a)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const today = todayIso()

  const todayAndOverdue = useMemo(
    () => agenda.items.filter((i) => !i.date || i.date <= today),
    [agenda.items, today],
  )

  const weekDates = useMemo(() => Array.from({ length: WEEK_DAYS }, (_, i) => addDays(today, i)), [today])

  const byDate = useMemo(() => {
    const map = new Map<string, AgendaItem[]>()
    for (const d of weekDates) map.set(d, [])
    for (const item of agenda.items) {
      if (!item.date) continue
      const bucket = map.get(item.date)
      if (bucket) bucket.push(item)
    }
    return map
  }, [agenda.items, weekDates])

  const handleToggleDone = async (id: string) => {
    await study.markDone(id)
    void load()
  }

  const handleAdd = async () => {
    const t = title.trim()
    if (!t) return
    setAdding(true)
    await study.addTask({ title: t, day: day || todayIso() })
    setTitle('')
    setAdding(false)
    void load()
  }

  return (
    <div className="mx-auto max-w-[1200px]">
      <div className="mb-6">
        <p className="label-mono mb-1">tasks · applications · assignments</p>
        <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Study Planner</h1>
      </div>

      {/* quick add */}
      <Panel className="mb-6">
        <div className="flex items-center gap-2 px-4 py-3">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void handleAdd() }}
            placeholder="Quick-add a task…"
            className="flex-1 bg-transparent text-[13px] text-hi placeholder:text-low focus:outline-none"
          />
          <input
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            className="rounded-md border border-line bg-transparent px-2 py-1 font-mono text-[12px] text-mid focus:outline-none"
          />
          <Btn kind="primary" onClick={() => void handleAdd()} disabled={adding || !title.trim()}>
            <span className="flex items-center gap-1.5">
              <Plus size={13} /> Add
            </span>
          </Btn>
        </div>
      </Panel>

      {error && (
        <Panel className="mb-6">
          <EmptyState title="Couldn't reach the study service." hint="Showing whatever loaded so far." />
        </Panel>
      )}

      {/* today + overdue */}
      <Panel className="mb-6">
        <PanelHead label="today · overdue" right={<Mono className="text-low">{todayAndOverdue.length} items</Mono>} />
        <div className="flex flex-col gap-px px-2 pb-3">
          {!loading && todayAndOverdue.length === 0 && (
            <EmptyState title="Nothing due today." hint="Add a task above, or check the week strip below." />
          )}
          {todayAndOverdue.map((item) => (
            <AgendaRow key={`${item.kind}-${item.id ?? item.title}`} item={item} onToggleDone={handleToggleDone} />
          ))}
        </div>
      </Panel>

      {/* week strip */}
      <Panel>
        <PanelHead label="next 7 days" />
        <div className="overflow-x-auto pb-3">
          <div className="flex min-w-max gap-3 px-4">
            {weekDates.map((d) => {
              const items = byDate.get(d) ?? []
              return (
                <div key={d} className="w-[220px] shrink-0">
                  <div className="mb-2 flex items-center justify-between px-1">
                    <span className="label-mono">{d === today ? 'today' : dayLabel(d)}</span>
                    <Mono className="text-low">{items.length}</Mono>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    {items.length === 0 && (
                      <div className="rounded-[10px] border border-dashed border-hairline py-4 text-center">
                        <Mono className="text-low">empty</Mono>
                      </div>
                    )}
                    {items.map((item) => (
                      <div key={`${item.kind}-${item.id ?? item.title}`} className="panel px-3 py-2">
                        <div className="mb-1 flex items-center gap-2">
                          <KindPill kind={item.kind} />
                          {item.kind === 'task' && item.id && (
                            <input
                              type="checkbox"
                              checked={false}
                              onChange={() => void handleToggleDone(item.id as string)}
                              className="ml-auto size-3.5 accent-black/70"
                              aria-label={`Mark "${item.title ?? 'task'}" done`}
                            />
                          )}
                        </div>
                        <p className="truncate text-[12.5px] text-mid">{item.title ?? '(untitled)'}</p>
                        {isToday(item.date) && <Mono className="text-low">today</Mono>}
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </Panel>

      <div className="mt-6">
        <GuidePanel compact />
      </div>
    </div>
  )
}

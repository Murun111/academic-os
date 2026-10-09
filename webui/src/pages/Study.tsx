import { useCallback, useEffect, useMemo, useState } from 'react'
import { Plus } from 'lucide-react'
import { study, kindTone, isOverdue, todayIso, addDaysIso as addDays, type Agenda, type AgendaItem } from '../lib/studyApi'
import { Btn, EmptyState, Mono, Panel, PanelHead, Pill } from '../components/ui'
import { GuidePanel } from '../components/GuidePanel'
import { ConfirmDelete, EditText } from '../components/CourseRows'

const WEEK_DAYS = 7

function dayLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return `${d.toLocaleDateString(undefined, { weekday: 'short' })} ${d.getDate()}`
}

// compact color coding for the week grid — dot instead of a wide pill
const KIND_COLOR: Record<AgendaItem['kind'], string> = {
  application: 'var(--color-pend)',
  assignment: 'var(--color-acc)',
  task: 'var(--color-low)',
}

function KindPill({ kind }: { kind: AgendaItem['kind'] }) {
  return <Pill tone={kindTone(kind)}>{kind}</Pill>
}

// The agenda carries completion in `meta`: tasks as `done`, assignments as
// `status`. Anything the backend doesn't send reads as not done.
function isItemDone(item: AgendaItem): boolean {
  const meta = item.meta ?? {}
  return meta.done === true || meta.status === 'done'
}

function AgendaRow({ item, onToggleDone, onDelete, onRename }: {
  item: AgendaItem
  onToggleDone?: (item: AgendaItem) => void
  onDelete?: (id: string) => void
  onRename?: (id: string, title: string) => void
}) {
  const isTask = item.kind === 'task'
  const done = isItemDone(item)
  return (
    <div className="flex items-center gap-3 rounded-[10px] px-3 py-2 hover:bg-ink/4">
      {isTask && item.id ? (
        <input
          type="checkbox"
          checked={isItemDone(item)}
          onChange={() => onToggleDone?.(item)}
          className="size-3.5 accent-ink/70"
          aria-label={`Mark "${item.title ?? 'task'}" done`}
        />
      ) : (
        <span className="inline-block size-3.5" />
      )}
      <KindPill kind={item.kind} />
      {isTask && item.id ? (
        <EditText
          value={item.title ?? ''}
          onCommit={(t) => onRename?.(item.id as string, t)}
          ariaLabel="Task title"
          className={`min-w-0 flex-1 text-[13px] ${done ? 'line-through opacity-60' : ''}`}
        />
      ) : (
        <span className="flex-1 truncate text-[13px] text-mid">{item.title ?? '(untitled)'}</span>
      )}
      {!done && item.date && isOverdue(item.date) && <Mono className="text-fail">overdue</Mono>}
      <Mono className="w-[76px] shrink-0 text-right text-low">{item.date ?? '—'}</Mono>
      {isTask && item.id ? (
        <ConfirmDelete onConfirm={() => onDelete?.(item.id as string)} label={`Delete ${item.title ?? 'task'}`} />
      ) : (
        <span className="inline-block size-3.5 shrink-0" />
      )}
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
  const [addError, setAddError] = useState('')

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
    // finished items from past days drop out; today's stay so they can be unticked
    () => agenda.items.filter((i) => (!i.date || i.date <= today) && (!isItemDone(i) || i.date === today)),
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

  const handleToggleDone = async (item: AgendaItem) => {
    if (!item.id) return
    if (isItemDone(item)) await study.reopen(item.id)
    else await study.markDone(item.id)
    void load()
  }

  const handleDelete = async (id: string) => {
    await study.deleteTask(id)
    void load()
  }

  const handleRename = async (id: string, newTitle: string) => {
    await study.updateTask(id, { title: newTitle })
    void load()
  }

  const handleAdd = async () => {
    const t = title.trim()
    if (!t) return
    setAdding(true)
    setAddError('')
    const created = await study.addTask({ title: t, day: day || todayIso() })
    setAdding(false)
    if (!created) {
      // keep what the student typed; they can press Add again
      setAddError('Could not save the task. Try again.')
      return
    }
    setTitle('')
    void load()
  }

  return (
    <div className="mx-auto max-w-[1200px]">
      <div className="mb-6">
        <p className="label-mono mb-1">tasks · applications · assignments</p>
        <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Study Planner</h1>
      </div>

      {/* quick add */}
      <div data-tour="study-quickadd">
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
        {addError && <p className="px-4 pb-3 text-[12.5px] text-fail">{addError}</p>}
      </Panel>
      </div>

      {error && (
        <Panel className="mb-6">
          <EmptyState title="Couldn't reach the study service." hint="Showing whatever loaded so far." />
        </Panel>
      )}

      {/* week at a glance — all 7 days fit the width, no scrolling */}
      <div data-tour="study-week">
      <Panel className="mb-6">
        <PanelHead label="next 7 days" />
        <div className="grid grid-cols-7 gap-2 px-4 pb-4">
          {weekDates.map((d) => {
            const items = byDate.get(d) ?? []
            const isTodayCol = d === today
            return (
              <div key={d} className={`min-w-0 rounded-[10px] p-1.5 ${isTodayCol ? 'bg-ink/4' : ''}`}>
                <div className="mb-1.5 flex items-baseline justify-between px-0.5">
                  <span className="label-mono">{isTodayCol ? 'today' : dayLabel(d)}</span>
                  {items.length > 0 && <Mono className="text-low">{items.length}</Mono>}
                </div>
                <div className="flex flex-col gap-1">
                  {items.length === 0 && (
                    <div className="rounded-md border border-dashed border-hairline py-1.5 text-center">
                      <Mono className="text-low">·</Mono>
                    </div>
                  )}
                  {items.map((item) => (
                    <div
                      key={`${item.kind}-${item.id ?? item.title}`}
                      title={`${item.kind}: ${item.title ?? '(untitled)'}`}
                      className="panel flex items-center gap-1.5 px-2 py-1.5"
                    >
                      <span
                        className="size-1.5 shrink-0 rounded-full"
                        style={{ background: KIND_COLOR[item.kind] }}
                      />
                      <p className="min-w-0 flex-1 truncate text-[12px] text-mid">{item.title ?? '(untitled)'}</p>
                      {item.kind === 'task' && item.id && (
                        <input
                          type="checkbox"
                          checked={isItemDone(item)}
                          onChange={() => void handleToggleDone(item)}
                          className="size-3 shrink-0 accent-ink/70"
                          aria-label={`Mark "${item.title ?? 'task'}" done`}
                        />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </Panel>
      </div>

      {/* today + overdue */}
      <Panel>
        <PanelHead label="today · overdue" right={<Mono className="text-low">{todayAndOverdue.length} items</Mono>} />
        <div className="flex flex-col gap-px px-2 pb-3">
          {!loading && todayAndOverdue.length === 0 && (
            <EmptyState title="Nothing due today." hint="Add a task above, or check the week above." />
          )}
          {todayAndOverdue.map((item) => (
            <AgendaRow
              key={`${item.kind}-${item.id ?? item.title}`}
              item={item}
              onToggleDone={(i) => void handleToggleDone(i)}
              onDelete={(id) => void handleDelete(id)}
              onRename={(id, t) => void handleRename(id, t)}
            />
          ))}
        </div>
      </Panel>

      <div className="mt-6">
        <GuidePanel compact />
      </div>
    </div>
  )
}

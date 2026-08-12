// Calendar — one month grid holding everything with a date: application
// deadlines, assignment due dates, study tasks, and the entrance exam.
// Read-only view; clicking an item jumps to the page that owns it.
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Btn, Mono, Panel } from '../components/ui'
import { applicationsApi, type Application } from '../lib/applicationsApi'
import { coursesApi } from '../lib/coursesApi'
import { study, type Task } from '../lib/studyApi'
import { useOs } from '../lib/store'
import { trackApplies, trackConfig } from '../lib/trackConfig'

interface CalItem {
  date: string // ISO day
  kind: 'application' | 'assignment' | 'task' | 'exam'
  title: string
  done?: boolean
  to: string // page that owns this item
}

const KIND_COLOR: Record<CalItem['kind'], string> = {
  application: 'var(--color-pend)',
  assignment: 'var(--color-acc)',
  task: 'var(--color-low)',
  exam: 'var(--color-fail)',
}

const KIND_LABEL: Record<CalItem['kind'], string> = {
  application: 'application deadline',
  assignment: 'assignment due',
  task: 'task',
  exam: 'exam',
}

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function Calendar() {
  const navigate = useNavigate()
  const stage = useOs((s) => s.stage)
  const track = useOs((s) => s.track)
  const testDate = useOs((s) => s.testDate)
  const trackCfg = trackApplies(stage) ? trackConfig(track) : null

  const today = new Date()
  const [anchor, setAnchor] = useState(new Date(today.getFullYear(), today.getMonth(), 1))
  const [items, setItems] = useState<CalItem[]>([])

  useEffect(() => {
    void Promise.all([
      applicationsApi.list(),
      coursesApi.listAssignments(),
      study.tasks(),
    ]).then(([apps, assignments, tasks]) => {
      const all: CalItem[] = []
      for (const a of apps as Application[]) {
        if (a.deadline) all.push({ date: a.deadline, kind: 'application', title: a.name, to: '/applications' })
      }
      for (const x of assignments.assignments) {
        if (x.due) all.push({ date: x.due, kind: 'assignment', title: x.title, done: x.status === 'done', to: '/courses' })
      }
      for (const t of tasks as Task[]) {
        if (t.day) all.push({ date: t.day, kind: 'task', title: t.title, done: t.done, to: '/study' })
      }
      if (trackCfg?.exam && testDate) {
        all.push({ date: testDate, kind: 'exam', title: `${trackCfg.exam} exam`, to: '/settings' })
      }
      setItems(all)
    })
  }, [trackCfg?.exam, testDate])

  const byDate = useMemo(() => {
    const m = new Map<string, CalItem[]>()
    for (const it of items) {
      const list = m.get(it.date) ?? []
      list.push(it)
      m.set(it.date, list)
    }
    return m
  }, [items])

  // 6-week grid starting on the Sunday before the 1st
  const cells = useMemo(() => {
    const first = new Date(anchor)
    const start = new Date(first)
    start.setDate(first.getDate() - first.getDay())
    return Array.from({ length: 42 }, (_, n) => {
      const d = new Date(start)
      d.setDate(start.getDate() + n)
      return { date: iso(d), day: d.getDate(), inMonth: d.getMonth() === anchor.getMonth() }
    })
  }, [anchor])

  const todayIso = iso(today)
  const monthLabel = anchor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
  const move = (delta: number) => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + delta, 1))

  return (
    <div className="mx-auto max-w-[1200px]">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <p className="label-mono mb-1">deadlines · assignments · tasks</p>
          <h1 className="text-[24px] font-semibold tracking-[-0.01em]">{monthLabel}</h1>
        </div>
        <div className="flex items-center gap-1.5">
          <Btn onClick={() => move(-1)}><ChevronLeft size={14} /></Btn>
          <Btn onClick={() => setAnchor(new Date(today.getFullYear(), today.getMonth(), 1))}>Today</Btn>
          <Btn onClick={() => move(1)}><ChevronRight size={14} /></Btn>
        </div>
      </div>

      <Panel className="p-3">
        <div className="mb-1 grid grid-cols-7">
          {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => (
            <span key={d} className="label-mono px-2 py-1">{d}</span>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-px">
          {cells.map((c) => {
            const dayItems = byDate.get(c.date) ?? []
            const isToday = c.date === todayIso
            return (
              <div
                key={c.date}
                className={`min-h-[96px] rounded-[10px] p-1.5 ${c.inMonth ? '' : 'opacity-40'} ${isToday ? 'bg-ink/5 ring-1 ring-ink/15' : ''}`}
              >
                <Mono className={`block px-0.5 ${isToday ? 'text-hi' : 'text-low'}`}>{c.day}</Mono>
                <div className="mt-0.5 flex flex-col gap-0.5">
                  {dayItems.slice(0, 3).map((it, n) => (
                    <button
                      key={n}
                      onClick={() => navigate(it.to)}
                      title={`${KIND_LABEL[it.kind]}: ${it.title}`}
                      className="flex min-w-0 items-center gap-1 rounded px-1 py-0.5 text-left hover:bg-ink/6"
                    >
                      <span className="size-1.5 shrink-0 rounded-full" style={{ background: KIND_COLOR[it.kind] }} />
                      <span className={`truncate text-[11.5px] leading-tight ${it.done ? 'text-low line-through' : 'text-mid'}`}>
                        {it.title}
                      </span>
                    </button>
                  ))}
                  {dayItems.length > 3 && (
                    <Mono className="px-1 text-low">+{dayItems.length - 3} more</Mono>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </Panel>

      <div className="mt-3 flex flex-wrap items-center gap-4 px-1">
        {(Object.keys(KIND_COLOR) as CalItem['kind'][]).map((k) => (
          <span key={k} className="flex items-center gap-1.5">
            <span className="size-1.5 rounded-full" style={{ background: KIND_COLOR[k] }} />
            <Mono className="text-low">{KIND_LABEL[k]}</Mono>
          </span>
        ))}
      </div>
    </div>
  )
}

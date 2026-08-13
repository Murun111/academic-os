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
  id: string // record id (empty for the synthetic exam item)
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
  const [expandedDays, setExpandedDays] = useState<Set<string>>(new Set())

  useEffect(() => {
    void Promise.all([
      applicationsApi.list(),
      coursesApi.listAssignments(),
      study.tasks(),
      coursesApi.listCourses(),
    ]).then(([apps, assignments, tasks, courseList]) => {
      const archivedCourses = new Set(courseList.courses.filter((c) => c.archived).map((c) => c.id))
      const all: CalItem[] = []
      for (const a of apps as Application[]) {
        if (a.deadline && !a.archived) all.push({ date: a.deadline, kind: 'application', title: a.name, id: a.id, to: `/applications?open=${a.id}` })
      }
      for (const x of assignments.assignments) {
        if (x.due && !archivedCourses.has(x.course_id)) all.push({ date: x.due, kind: 'assignment', title: x.title, done: x.status === 'done', id: x.id, to: `/courses?open=${x.course_id}` })
      }
      for (const t of tasks as Task[]) {
        if (t.day) all.push({ date: t.day, kind: 'task', title: t.title, done: t.done, id: t.id, to: '/study' })
      }
      if (trackCfg?.exam && testDate) {
        all.push({ date: testDate, kind: 'exam', title: `${trackCfg.exam} exam`, id: '', to: '/settings' })
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
  const toggleDay = (date: string) =>
    setExpandedDays((prev) => {
      const next = new Set(prev)
      if (next.has(date)) next.delete(date)
      else next.add(date)
      return next
    })

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

      <div data-tour="calendar-grid">
      <Panel className="p-3">
        <div className="mb-1 grid grid-cols-7">
          {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => (
            <span key={d} className="label-mono px-2 py-1">{d}</span>
          ))}
        </div>
        {/* gap-px over an ink-tinted backdrop draws the day gridlines; ink/18
            (not the hairline token) so the lines actually read between white cells */}
        <div className="grid grid-cols-7 gap-px overflow-hidden rounded-[10px] border border-ink/18 bg-ink/18">
          {cells.map((c) => {
            const dayItems = byDate.get(c.date) ?? []
            const isToday = c.date === todayIso
            const isExpanded = expandedDays.has(c.date)
            const visibleItems = isExpanded ? dayItems : dayItems.slice(0, 3)
            return (
              <div
                key={c.date}
                className={`min-h-[96px] p-1.5 ${
                  isToday ? 'bg-raise ring-2 ring-acc/60 ring-inset' : c.inMonth ? 'bg-raise' : 'bg-raise2'
                }`}
              >
                <Mono className={`block px-0.5 ${isToday ? 'text-hi' : c.inMonth ? 'text-low' : 'text-low opacity-60'}`}>{c.day}</Mono>
                <div className={`mt-0.5 flex flex-col gap-0.5 ${c.inMonth ? '' : 'opacity-60'}`}>
                  {visibleItems.map((it, n) => (
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
                    <button
                      onClick={() => toggleDay(c.date)}
                      className="px-1 text-left font-mono text-[11px] text-low hover:text-mid"
                    >
                      {isExpanded ? 'show less' : `+${dayItems.length - 3} more`}
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </Panel>
      </div>

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

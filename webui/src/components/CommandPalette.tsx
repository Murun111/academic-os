import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import {
  LayoutGrid, MessageSquare, Bot, ShieldCheck, Settings as SettingsIcon,
  GraduationCap, BookOpen, CalendarCheck, CalendarDays, Files, Sparkles, Brain, Play, Check, X as XIcon,
} from 'lucide-react'
import { useOs } from '../lib/store'
import { stageConfig } from '../lib/stageConfig'
import { trackApplies, trackConfig } from '../lib/trackConfig'
import { Kbd } from './ui'
import { applicationsApi, type Application } from '../lib/applicationsApi'
import { coursesApi, type Course } from '../lib/coursesApi'
import { documentsApi, type Document } from '../lib/documentsApi'

interface Cmd {
  id: string
  group: 'Go to' | 'Run agent' | 'Approvals' | 'Applications' | 'Courses' | 'Documents'
  label: string
  hint?: string
  /** extra words that should match this command (e.g. the generic "applications" for a stage-renamed page) */
  keywords?: string
  to?: string
  icon: React.ComponentType<{ size?: number; strokeWidth?: number }>
  action: () => void
}

interface SearchData {
  applications: Application[]
  courses: Course[]
  documents: Document[]
}

const EMPTY_SEARCH_DATA: SearchData = { applications: [], courses: [], documents: [] }

export function CommandPalette() {
  const open = useOs((s) => s.paletteOpen)
  const setOpen = useOs((s) => s.setPalette)
  const agents = useOs((s) => s.agents)
  const approvals = useOs((s) => s.approvals)
  const runAgent = useOs((s) => s.runAgent)
  const decide = useOs((s) => s.decide)
  const stage = useOs((s) => s.stage)
  const track = useOs((s) => s.track)
  const appsLabel = (trackApplies(stage) ? trackConfig(track)?.appsTitle : undefined) ?? stageConfig(stage).appsTitle
  const navigate = useNavigate()

  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [searchData, setSearchData] = useState<SearchData>(EMPTY_SEARCH_DATA)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen(!useOs.getState().paletteOpen)
      }
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setOpen])

  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
      setTimeout(() => inputRef.current?.focus(), 30)
    }
  }, [open])

  // fetch searchable data once per palette-open, not on every keystroke
  useEffect(() => {
    if (!open) return
    let cancelled = false
    Promise.all([applicationsApi.list(), coursesApi.listCourses(), documentsApi.list()]).then(
      ([applications, coursesRes, documents]) => {
        if (cancelled) return
        setSearchData({ applications, courses: coursesRes.courses, documents })
      },
    )
    return () => {
      cancelled = true
    }
  }, [open])

  const commands = useMemo<Cmd[]>(() => {
    const go = (id: string, label: string, icon: Cmd['icon'], to: string, keywords?: string): Cmd =>
      ({ id, group: 'Go to', label, keywords, to, icon, action: () => navigate(to) })
    const navUnsorted: Cmd[] = [
      go('g-dash', 'Dashboard', LayoutGrid, '/'),
      go('g-apps', appsLabel, GraduationCap, '/applications', 'applications programs colleges schools'),
      go('g-courses', 'Courses', BookOpen, '/courses'),
      go('g-study', 'Study', CalendarCheck, '/study'),
      go('g-learning', 'Learning', Brain, '/learning'),
      go('g-cal', 'Calendar', CalendarDays, '/calendar'),
      go('g-docs', 'Documents', Files, '/documents'),
      go('g-routines', 'Routines', Sparkles, '/routines'),
      go('g-chat', 'Chat', MessageSquare, '/chat'),
      go('g-agents', 'Assistants', Bot, '/agents'),
      go('g-appr', 'Approvals', ShieldCheck, '/approvals'),
      go('g-settings', 'Settings', SettingsIcon, '/settings'),
    ]
    // same order as the sidebar (stage-aware); anything not listed keeps its place after
    const order = stageConfig(stage).navOrder
    const rank = (c: Cmd) => { const i = order.indexOf(c.to ?? ''); return i === -1 ? order.length : i }
    const nav = [...navUnsorted].sort((a, b) => rank(a) - rank(b))
    const run: Cmd[] = agents.map((a) => ({
      id: `run-${a.name}`, group: 'Run agent', label: a.name, hint: a.state,
      icon: Play, action: () => void runAgent(a.name),
    }))
    const appr: Cmd[] = approvals.flatMap((a) => [
      { id: `ok-${a.id}`, group: 'Approvals' as const, label: `Approve ${a.tool}`, hint: a.agent, icon: Check, action: () => void decide(a.id, true) },
      { id: `no-${a.id}`, group: 'Approvals' as const, label: `Deny ${a.tool}`, hint: a.agent, icon: XIcon, action: () => void decide(a.id, false) },
    ])
    return [...nav, ...run, ...appr]
  }, [agents, approvals, navigate, runAgent, decide, appsLabel, stage])

  const searchGroups = useMemo<Cmd[]>(() => {
    const n = query.trim().toLowerCase()
    if (!n) return []
    const apps: Cmd[] = searchData.applications
      .filter((a) => a.name.toLowerCase().includes(n) || a.org.toLowerCase().includes(n))
      .slice(0, 6)
      .map((a) => ({
        id: `sr-app-${a.id}`, group: 'Applications', label: a.name, hint: a.org,
        icon: GraduationCap, action: () => navigate(`/applications?open=${a.id}`),
      }))
    const courses: Cmd[] = searchData.courses
      .filter((c) => c.name.toLowerCase().includes(n))
      .slice(0, 6)
      .map((c) => ({
        id: `sr-course-${c.id}`, group: 'Courses', label: c.name, hint: c.term,
        icon: BookOpen, action: () => navigate(`/courses?open=${c.id}`),
      }))
    const docs: Cmd[] = searchData.documents
      .filter((d) => d.title.toLowerCase().includes(n))
      .slice(0, 6)
      .map((d) => ({
        id: `sr-doc-${d.id}`, group: 'Documents', label: d.title, hint: d.kind,
        icon: Files, action: () => navigate('/documents'),
      }))
    return [...apps, ...courses, ...docs]
  }, [query, searchData, navigate])

  const filtered = useMemo(() => {
    if (!query.trim()) return commands
    const n = query.toLowerCase()
    const staticMatches = commands.filter((c) =>
      (c.label + ' ' + c.group + ' ' + (c.hint ?? '') + ' ' + (c.keywords ?? '')).toLowerCase().includes(n),
    )
    return [...staticMatches, ...searchGroups]
  }, [commands, query, searchGroups])

  const pick = (c: Cmd) => {
    setOpen(false)
    c.action()
  }

  const onInputKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, filtered.length - 1)) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    if (e.key === 'Enter' && filtered[active]) pick(filtered[active])
  }

  // focus trap: the palette is arrow/enter-driven; Tab must not escape the overlay
  const trapTab = (e: React.KeyboardEvent) => {
    if (e.key === 'Tab') e.preventDefault()
  }

  let lastGroup = ''
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/20 pt-[16vh]"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          transition={{ duration: 0.16 }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false) }}
          onKeyDown={trapTab}
          role="dialog"
          aria-modal="true"
          aria-label="Command palette"
        >
          <motion.div
            className="glass-strong w-[560px] overflow-hidden rounded-[18px]"
            initial={{ opacity: 0, y: 10, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.99 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="flex items-center gap-3 border-b border-hairline px-4">
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => { setQuery(e.target.value); setActive(0) }}
                onKeyDown={onInputKey}
                placeholder="Jump, run, approve…"
                className="h-12 flex-1 bg-transparent text-[14px] text-hi outline-none placeholder:text-low"
              />
              <Kbd>esc</Kbd>
            </div>
            <div className="max-h-[46vh] overflow-y-auto py-2">
              {filtered.length === 0 && (
                <p className="px-4 py-6 text-center text-[13px] text-low">Nothing matches “{query}”.</p>
              )}
              {filtered.map((c, i) => {
                const header = c.group !== lastGroup ? c.group : null
                lastGroup = c.group
                const Icon = c.icon
                return (
                  <div key={c.id}>
                    {header && <p className="label-mono px-4 pt-3 pb-1.5">{header}</p>}
                    <button
                      onMouseEnter={() => setActive(i)}
                      onClick={() => pick(c)}
                      className={`flex w-full items-center gap-3 px-4 py-2 text-left text-[13.5px] transition-colors duration-100 ${
                        i === active ? 'bg-ink/6 text-hi' : 'text-mid'
                      }`}
                    >
                      <Icon size={14} strokeWidth={1.75} />
                      <span className="flex-1">{c.label}</span>
                      {c.hint && <span className="font-mono text-[11px] text-low">{c.hint}</span>}
                    </button>
                  </div>
                )
              })}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

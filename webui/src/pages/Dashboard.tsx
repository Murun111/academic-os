import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { NO_MOTION } from '../lib/motion'
import { ArrowUpRight, Play } from 'lucide-react'
import { useOs } from '../lib/store'
import { stageConfig } from '../lib/stageConfig'
import { trackApplies, trackConfig, daysToTest } from '../lib/trackConfig'
import { applicationsApi, APPLICATION_STATUSES, type Application } from '../lib/applicationsApi'
import { coursesApi } from '../lib/coursesApi'
import { GettingStarted } from '../components/GettingStarted'
import { study, kindTone, isOverdue, isToday, type AgendaItem } from '../lib/studyApi'
import { Btn, EmptyState, Mono, Panel, PanelHead, Pill, ServiceRow, StatusDot, timeAgo } from '../components/ui'
import { GuidePanel } from '../components/GuidePanel'

const STATUS_LABEL: Record<string, string> = {
  researching: 'Researching', preparing: 'Preparing', submitted: 'Submitted',
  interview: 'Interview', decision: 'Decision',
}

const stagger = NO_MOTION
  ? ({} as const)
  : ({
      variants: {
        hidden: { opacity: 0, y: 10 },
        show: (i: number) => ({
          opacity: 1, y: 0,
          transition: { delay: i * 0.04, duration: 0.3, ease: [0.22, 1, 0.36, 1] as const },
        }),
      },
      initial: 'hidden',
      animate: 'show',
    } as const)

function daysUntil(deadline: string): number {
  return Math.ceil((new Date(deadline).getTime() - Date.now()) / 86_400_000)
}

// where an agenda row sends you when you click it
function agendaHref(item: AgendaItem): string {
  if (item.kind === 'assignment') return '/courses'
  if (item.kind === 'task') return '/study'
  return item.id ? `/applications?open=${item.id}` : '/applications'
}

export function Dashboard() {
  const { agents, events, approvals, health, runAgent, stage, userName, track, testDate } = useOs()
  const trackCfg = trackApplies(stage) ? trackConfig(track) : null
  const examDays = daysToTest(testDate)
  const cfg = stageConfig(stage)
  const [deadlines, setDeadlines] = useState<Application[]>([])
  const [pipeline, setPipeline] = useState<Application[]>([])
  const [agenda, setAgenda] = useState<AgendaItem[]>([])
  const [coursesCount, setCoursesCount] = useState(0)
  const [onboardLoaded, setOnboardLoaded] = useState(false)

  useEffect(() => {
    void applicationsApi.deadlines(45).then(setDeadlines)
    void study.agenda(7).then((a) => setAgenda(a.items))
    void Promise.all([applicationsApi.list(), coursesApi.listCourses()]).then(([apps, c]) => {
      setPipeline(apps.filter((a) => !a.archived))
      setCoursesCount(c.courses.filter((x) => !x.archived).length)
      setOnboardLoaded(true)
    })
  }, [])

  const hour = new Date().getHours()
  const daypart = hour < 5 ? 'night' : hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening'
  // done tasks stay in the agenda (Study renders them checked) — the dashboard
  // shows only what still needs doing
  const todayItems = agenda.filter(
    (i) => (isToday(i.date) || isOverdue(i.date)) && i.meta?.done !== true,
  )

  return (
    <div className="mx-auto max-w-[1200px]">
      {/* header strip: no panel, just air */}
      <div className="mb-6 flex items-end justify-between">
        <div>
          <p className="label-mono mb-1">
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
          <h1 className="text-[24px] font-semibold tracking-[-0.01em]">
            Good {daypart}{userName ? `, ${userName.split(' ')[0]}` : ''}.
          </h1>
        </div>
        <div className="flex items-center gap-2">
          {trackCfg?.exam && examDays != null && (
            <Link
              to="/settings"
              title="Exam date — change in Settings"
              className={`rounded-lg border px-3 py-1.5 font-mono text-[12px] ${
                examDays <= 14 ? 'border-fail/25 text-fail' : 'border-line text-mid'
              }`}
            >
              {trackCfg.exam} in {examDays}d
            </Link>
          )}
          {approvals.length > 0 && (
            <Link
              to="/approvals"
              className="flex items-center gap-2 rounded-lg border border-pend/25 bg-pend/8 px-3 py-1.5 text-[13px] text-pend transition-colors hover:bg-pend/14"
            >
              <StatusDot state="pending" live />
              {approvals.length} waiting on you
              <ArrowUpRight size={13} />
            </Link>
          )}
        </div>
      </div>

      <GettingStarted appsCount={pipeline.length} coursesCount={coursesCount} loaded={onboardLoaded} />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_340px]">
        {/* ---------------- left column ---------------- */}
        <div className="flex flex-col gap-5">
          {/* next deadlines — the thing a student must never miss */}
          <motion.div custom={0} {...stagger}>
            <Panel>
              <PanelHead
                label="next deadlines"
                right={<Link to="/applications" className="text-[12px] text-low hover:text-mid">{cfg.appsTitle.toLowerCase()}</Link>}
              />
              <div className="flex flex-col gap-1.5 px-5 pb-4">
                {deadlines.slice(0, 5).map((d) => {
                  const days = d.deadline ? daysUntil(d.deadline) : null
                  const urgent = days !== null && days < 7
                  return (
                    <div key={d.id} className="flex items-baseline gap-3">
                      <span className="flex-1 truncate text-[13.5px] text-hi">{d.name}</span>
                      <Pill>{d.type}</Pill>
                      <Mono className={urgent ? 'text-fail' : 'text-low'}>
                        {d.deadline} · {days}d
                      </Mono>
                    </div>
                  )
                })}
                {deadlines.length === 0 && (
                  <EmptyState title="No deadlines in the next 45 days." hint="Add applications to track them here." />
                )}
                {deadlines.length > 5 && (
                  <Link to="/applications" className="pt-1 text-[12px] text-low hover:text-mid">
                    Showing 5 of {deadlines.length} — see all
                  </Link>
                )}
              </div>
            </Panel>
          </motion.div>

          {/* today's agenda: tasks + assignments + application deadlines merged */}
          <motion.div custom={1} {...stagger}>
            <Panel>
              <PanelHead
                label="today"
                right={<Link to="/study" className="text-[12px] text-low hover:text-mid">study</Link>}
              />
              <div className="flex flex-col gap-1.5 px-5 pb-4">
                {todayItems.slice(0, 6).map((i) => (
                  <Link
                    key={`${i.kind}-${i.id}`}
                    to={agendaHref(i)}
                    className="-mx-1 flex items-baseline gap-3 rounded-lg px-1 py-0.5 transition-colors hover:bg-ink/5"
                  >
                    <Pill tone={kindTone(i.kind)}>{i.kind}</Pill>
                    <span className="flex-1 truncate text-[13px] text-mid">{i.title}</span>
                    {i.date && isOverdue(i.date) && <Mono className="text-fail">overdue</Mono>}
                  </Link>
                ))}
                {todayItems.length === 0 && <EmptyState title="Nothing due today. Breathe." />}
              </div>
            </Panel>
          </motion.div>

          {/* pipeline snapshot + agents share a row */}
          <div className="grid grid-cols-[1fr_1.2fr] gap-5">
            <motion.div custom={2} {...stagger}>
              <Panel className="h-full">
                <PanelHead label="pipeline" />
                <div className="flex flex-col gap-1.5 px-5 pb-4">
                  {APPLICATION_STATUSES.map((s) => {
                    const n = pipeline.filter((p) => p.status === s).length
                    return (
                      <div key={s} className="flex items-baseline justify-between">
                        <span className="text-[13px] text-mid">{STATUS_LABEL[s]}</span>
                        <Mono className={n > 0 ? 'text-hi' : 'text-low'}>{n}</Mono>
                      </div>
                    )
                  })}
                </div>
              </Panel>
            </motion.div>

            <motion.div custom={3} {...stagger}>
              <Panel className="h-full">
                <PanelHead
                  label="routines"
                  right={<Link to="/agents" className="text-[12px] text-low hover:text-mid">all</Link>}
                />
                <div className="flex flex-col gap-px px-2 pb-3">
                  {agents.map((a) => (
                    <div key={a.name} className="group flex items-center gap-2.5 rounded-[10px] px-3 py-2 hover:bg-ink/4">
                      <StatusDot state={a.state} live={a.state === 'running'} />
                      <Mono className="flex-1 truncate text-mid">{a.name}</Mono>
                      <Mono className="text-low group-hover:hidden">{a.lastRun ? timeAgo(a.lastRun) : '—'}</Mono>
                      <button
                        onClick={() => void runAgent(a.name)}
                        className="hidden items-center gap-1 font-mono text-[11px] text-mid group-hover:flex hover:text-hi"
                      >
                        <Play size={11} /> run
                      </button>
                    </div>
                  ))}
                  {agents.length === 0 && <EmptyState title="No routines installed." />}
                </div>
              </Panel>
            </motion.div>
          </div>
        </div>

        {/* ---------------- right column: the pulse ---------------- */}
        <div className="flex min-h-0 flex-col gap-5">
          <motion.div custom={1} {...stagger}>
            <Panel>
              <PanelHead label="services" />
              <div className="px-5 pb-3">
                {health ? (
                  <>
                    <ServiceRow name="app server" state={health.backend} />
                    <ServiceRow name="local ai" state={health.ollama} />
                  </>
                ) : (
                  <>
                    <div className="flex items-center justify-between py-1">
                      <Mono className="text-mid">app server</Mono>
                      <span className="flex items-center gap-2">
                        <StatusDot state="checking" />
                        <Mono className="text-low">checking…</Mono>
                      </span>
                    </div>
                    <div className="flex items-center justify-between py-1">
                      <Mono className="text-mid">local ai</Mono>
                      <span className="flex items-center gap-2">
                        <StatusDot state="checking" />
                        <Mono className="text-low">checking…</Mono>
                      </span>
                    </div>
                  </>
                )}
              </div>
            </Panel>
          </motion.div>

          <motion.div custom={2} {...stagger} className="min-h-0 flex-1">
            <Panel className="flex h-full max-h-[calc(100vh-320px)] flex-col">
              <PanelHead
                label="activity"
                right={
                  <span className="flex items-center gap-1.5">
                    <StatusDot state="running" live />
                    <Mono className="text-low">live</Mono>
                  </span>
                }
              />
              <div className="flex-1 overflow-y-auto px-2 pt-1 pb-2">
                {events.map((e) => (
                  <div
                    key={e.id}
                    className="rounded-lg px-3 py-1.5"
                    style={{ animation: 'row-flash 1.2s ease-out' }}
                  >
                    <div className="flex items-center gap-2">
                      <Mono className="text-low">{timeAgo(e.t)}</Mono>
                      <Pill>{e.kind}</Pill>
                      {e.agent && <Mono className="text-low">{e.agent}</Mono>}
                    </div>
                    <p className="mt-0.5 text-[12.5px] leading-snug text-mid">{e.message}</p>
                  </div>
                ))}
                {events.length === 0 && <EmptyState title="Waiting for the first event…" />}
              </div>
            </Panel>
          </motion.div>

          {approvals.length > 0 && (
            <motion.div custom={3} {...stagger}>
              <Panel>
                <PanelHead label="next approval" />
                <div className="px-5 pb-4">
                  <p className="mb-1 text-[13px] text-hi">{approvals[0].tool}</p>
                  <p className="mb-3 text-[12px] leading-relaxed text-low">{approvals[0].reason}</p>
                  <div className="flex gap-2">
                    <Btn kind="primary" onClick={() => void useOs.getState().decide(approvals[0].id, true)}>Approve</Btn>
                    <Btn kind="danger" onClick={() => void useOs.getState().decide(approvals[0].id, false)}>Deny</Btn>
                  </div>
                </div>
              </Panel>
            </motion.div>
          )}

          <GuidePanel />
        </div>
      </div>
    </div>
  )
}

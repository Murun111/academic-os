import { NavLink } from 'react-router-dom'
import {
  LayoutGrid, MessageSquare, Bot, ShieldCheck, Settings,
  Command, GraduationCap, BookOpen, CalendarCheck, CalendarDays, Files, Sparkles,
} from 'lucide-react'
import { useOs } from '../lib/store'
import { stageConfig, STAGES } from '../lib/stageConfig'
import { trackApplies, trackConfig } from '../lib/trackConfig'
import { Kbd, StatusDot } from './ui'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutGrid, end: true },
  { to: '/applications', label: 'Applications', icon: GraduationCap },
  { to: '/courses', label: 'Courses', icon: BookOpen },
  { to: '/study', label: 'Study', icon: CalendarCheck },
  { to: '/calendar', label: 'Calendar', icon: CalendarDays },
  { to: '/documents', label: 'Documents', icon: Files },
  { to: '/routines', label: 'Routines', icon: Sparkles },
  { to: '/chat', label: 'Chat', icon: MessageSquare },
  { to: '/agents', label: 'Assistants', icon: Bot },
  { to: '/approvals', label: 'Approvals', icon: ShieldCheck },
]

export function Sidebar() {
  const approvals = useOs((s) => s.approvals)
  const agents = useOs((s) => s.agents)
  const health = useOs((s) => s.health)
  const setPalette = useOs((s) => s.setPalette)
  const stage = useOs((s) => s.stage)
  const openStagePicker = useOs((s) => s.openStagePicker)
  const running = agents.filter((a) => a.state === 'running').length

  // stage-aware nav order: configured paths first (in order), the rest keep
  // their default relative order after them
  const order = stageConfig(stage).navOrder
  const nav = [...NAV].sort((a, b) => {
    const ia = order.indexOf(a.to)
    const ib = order.indexOf(b.to)
    return (ia === -1 ? order.length : ia) - (ib === -1 ? order.length : ib)
  })
  // stage-aware label (Colleges/Programs), further tailored by track (Med Schools)
  const track = useOs((s) => s.track)
  const trackCfg = trackApplies(stage) ? trackConfig(track) : null
  const appsTitle = trackCfg?.appsTitle ?? stageConfig(stage).appsTitle

  return (
    <aside className="glass fixed top-4 bottom-4 left-4 z-20 flex w-[60px] flex-col rounded-[18px] px-2 py-4 lg:w-[218px] lg:px-3">
      {/* system vitals instead of a logo: the OS introduces itself by its state */}
      <div className="mb-4 flex items-center justify-center lg:justify-between lg:px-2.5">
        <span className="flex items-center gap-2">
          <StatusDot state={health?.backend ?? 'ok'} live={running > 0} />
          <span className="hidden font-mono text-[11px] tracking-[0.08em] text-mid uppercase lg:inline">
            {running > 0 ? `${running} working` : 'all quiet'}
          </span>
        </span>
      </div>

      <nav data-tour="nav" className="flex flex-1 flex-col gap-0.5">
        {nav.map(({ to, label: rawLabel, icon: Icon, end }) => {
          const label = to === '/applications' ? appsTitle : rawLabel
          return (
          <NavLink
            key={to}
            to={to}
            end={end}
            title={label}
            className={({ isActive }) =>
              `group relative flex items-center justify-center gap-2.5 rounded-[10px] px-0 py-[7px] text-[13px] transition-colors duration-150 lg:justify-start lg:px-2.5 ${
                isActive ? 'bg-ink/6 text-hi' : 'text-mid hover:bg-ink/4 hover:text-hi'
              }`
            }
          >
            <Icon size={15} strokeWidth={1.75} className="shrink-0 opacity-70 group-hover:opacity-100" />
            <span className="hidden flex-1 lg:inline">{label}</span>
            {label === 'Approvals' && approvals.length > 0 && (
              <>
                <span className="hidden rounded-full bg-pend/15 px-1.5 font-mono text-[10.5px] text-pend lg:inline">
                  {approvals.length}
                </span>
                {/* rail mode: a bare amber tick instead of the count */}
                <span className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-pend lg:hidden" />
              </>
            )}
          </NavLink>
          )
        })}
      </nav>

      <NavLink
        to="/settings"
        title="Settings"
        className={({ isActive }) =>
          `mb-1 flex items-center justify-center gap-2.5 rounded-[10px] px-0 py-[7px] text-[13px] transition-colors duration-150 lg:justify-start lg:px-2.5 ${
            isActive ? 'bg-ink/6 text-hi' : 'text-mid hover:bg-ink/4 hover:text-hi'
          }`
        }
      >
        <Settings size={15} strokeWidth={1.75} className="shrink-0 opacity-70" />
        <span className="hidden flex-1 lg:inline">Settings</span>
      </NavLink>

      {stage && (
        <button
          data-tour="stage-pill"
          onClick={() => openStagePicker(true)}
          title="Change stage"
          className="mb-1 flex items-center justify-center rounded-[10px] px-0 py-1.5 font-mono text-[10.5px] tracking-[0.08em] text-low uppercase transition-colors duration-150 hover:bg-ink/4 hover:text-mid lg:justify-start lg:px-2.5"
        >
          {STAGES[stage].label}
        </button>
      )}

      <button
        onClick={() => setPalette(true)}
        title="Command palette (⌘K)"
        className="mt-3 flex items-center justify-center rounded-[10px] border border-line px-0 py-2 text-[12.5px] text-low transition-colors duration-150 hover:border-ink/15 hover:text-mid lg:justify-between lg:px-2.5"
      >
        <span className="flex items-center gap-2">
          <Command size={13} strokeWidth={1.75} />
          <span className="hidden lg:inline">Anything</span>
        </span>
        <span className="hidden lg:inline"><Kbd>⌘K</Kbd></span>
      </button>
    </aside>
  )
}

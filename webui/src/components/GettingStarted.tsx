// First-run "start here" checklist — shows on the Dashboard until the three
// setup steps are done (or the student hides it). No new state on the server:
// each step's done-ness is derived from data that already loads.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, X } from 'lucide-react'
import { Panel, PanelHead } from './ui'
import { useOs } from '../lib/store'

const DISMISS_KEY = 'academicos.gettingStartedHidden'

interface Step {
  label: string
  done: boolean
  to?: string
  onClick?: () => void
}

export function GettingStarted({ appsCount, coursesCount, loaded }: {
  appsCount: number
  coursesCount: number
  loaded: boolean
}) {
  const stage = useOs((s) => s.stage)
  const openStagePicker = useOs((s) => s.openStagePicker)
  const [hidden, setHidden] = useState(() => localStorage.getItem(DISMISS_KEY) === '1')

  const steps: Step[] = [
    { label: 'Tell us where you are — high school, undergrad, gap year…', done: stage !== null, onClick: () => openStagePicker(true) },
    { label: 'Add your first application or scholarship', done: appsCount > 0, to: '/applications' },
    { label: 'Add your courses, or connect Canvas in Settings', done: coursesCount > 0, to: '/courses' },
  ]
  const allDone = steps.every((s) => s.done)

  if (!loaded || hidden || allDone) return null

  const dismiss = () => {
    localStorage.setItem(DISMISS_KEY, '1')
    setHidden(true)
  }

  return (
    <Panel className="mb-5">
      <PanelHead
        label="start here"
        right={
          <button onClick={dismiss} title="Hide this" className="text-low hover:text-mid">
            <X size={14} />
          </button>
        }
      />
      <div className="flex flex-col gap-1 px-3 pb-3">
        {steps.map((s) => {
          const inner = (
            <>
              <span className={`flex size-4 shrink-0 items-center justify-center rounded-full border ${
                s.done ? 'border-transparent bg-acc/20 text-acc' : 'border-line text-transparent'
              }`}>
                <Check size={11} />
              </span>
              <span className={`text-[13px] ${s.done ? 'text-low line-through' : 'text-mid'}`}>{s.label}</span>
            </>
          )
          const cls = 'flex items-center gap-2.5 rounded-[10px] px-2 py-1.5 text-left hover:bg-ink/4'
          return s.to && !s.done ? (
            <Link key={s.label} to={s.to} className={cls}>{inner}</Link>
          ) : (
            <button key={s.label} onClick={s.done ? undefined : s.onClick} className={cls} disabled={s.done}>
              {inner}
            </button>
          )
        })}
        <p className="mt-1 px-2 text-[12px] text-low">
          Then try <span className="text-mid">Find scholarships</span> on the applications page —
          the scout searches the web while you do something else.
        </p>
      </div>
    </Panel>
  )
}

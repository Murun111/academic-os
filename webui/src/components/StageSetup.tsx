// First-launch stage question + reopenable stage picker.
// Shows automatically when the profile has no stage yet; afterwards it opens
// from the Sidebar stage pill. Picking undergrad/beyond on first run asks one
// follow-up — what's next (pre-med, pre-law, …) — which tailors the app.
import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { GraduationCap, BookOpen, Briefcase, FlaskConical, Rocket } from 'lucide-react'
import { useOs } from '../lib/store'
import { STAGES, STAGE_ORDER, type Stage } from '../lib/stageConfig'
import { TRACKS, TRACK_ORDER, trackApplies } from '../lib/trackConfig'
import { TOUR_DONE_KEY } from './Tour'

const ICONS: Record<Stage, typeof GraduationCap> = {
  highschool: GraduationCap,
  undergrad: BookOpen,
  gapyear: Briefcase,
  grad: FlaskConical,
  beyond: Rocket,
}

export function StageSetup() {
  const stage = useOs((s) => s.stage)
  const stageLoaded = useOs((s) => s.stageLoaded)
  const pickerOpen = useOs((s) => s.stagePickerOpen)
  const setStage = useOs((s) => s.setStage)
  const setTrack = useOs((s) => s.setTrack)
  const openPicker = useOs((s) => s.openStagePicker)
  const setTour = useOs((s) => s.setTour)
  // second onboarding question, shown after picking undergrad/beyond first-run
  const [askTrack, setAskTrack] = useState(false)

  const firstRun = stageLoaded && stage === null
  const open = firstRun || pickerOpen || askTrack

  // onboarding just finished → start the guided tour (once, ever)
  const maybeStartTour = () => {
    if (!localStorage.getItem(TOUR_DONE_KEY)) setTour(true)
  }

  const pickStage = async (key: Stage) => {
    const wasFirstRun = firstRun
    await setStage(key)
    if (wasFirstRun) {
      if (trackApplies(key)) setAskTrack(true)
      else maybeStartTour()
    }
  }

  const pickTrack = async (t: (typeof TRACK_ORDER)[number] | null) => {
    if (t) await setTrack(t)
    setAskTrack(false)
    maybeStartTour()
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          transition={{ duration: 0.16 }}
          onMouseDown={(e) => {
            // first run must answer; reopened picker can be dismissed
            if (!firstRun && !askTrack && e.target === e.currentTarget) openPicker(false)
          }}
          role="dialog"
          aria-modal="true"
          aria-label={askTrack ? 'What comes next' : 'Choose your stage'}
        >
          <motion.div
            className="glass-strong w-[520px] rounded-[18px] p-6"
            initial={{ opacity: 0, y: 10, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.99 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            {askTrack ? (
              <>
                <p className="label-mono mb-1">one more thing</p>
                <h1 className="mb-1 text-[20px] font-semibold tracking-[-0.01em]">
                  What comes after?
                </h1>
                <p className="mb-5 text-[13px] text-mid">
                  This tailors your pipeline and checklists. Change it anytime in Settings.
                </p>
                <div className="grid grid-cols-2 gap-3">
                  {TRACK_ORDER.map((t) => (
                    <button
                      key={t}
                      onClick={() => void pickTrack(t)}
                      className="rounded-[12px] border border-line p-4 text-left transition-colors duration-150 hover:border-ink/15 hover:bg-ink/4"
                    >
                      <p className="text-[14px] font-medium">{TRACKS[t].label}</p>
                      <p className="mt-0.5 text-[12px] text-low">{TRACKS[t].tagline}</p>
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <>
                <p className="label-mono mb-1">welcome</p>
                <h1 className="mb-1 text-[20px] font-semibold tracking-[-0.01em]">
                  What are you working toward?
                </h1>
                <p className="mb-5 text-[13px] text-mid">
                  This shapes what you see first. Change it anytime from the sidebar.
                </p>
                <div className="grid grid-cols-2 gap-3">
                  {STAGE_ORDER.map((key) => {
                    const cfg = STAGES[key]
                    const Icon = ICONS[key]
                    const active = stage === key
                    return (
                      <button
                        key={key}
                        onClick={() => void pickStage(key)}
                        className={`rounded-[12px] border p-4 text-left transition-colors duration-150 ${
                          active
                            ? 'border-ink/25 bg-ink/6'
                            : 'border-line hover:border-ink/15 hover:bg-ink/4'
                        }`}
                      >
                        <Icon size={18} strokeWidth={1.75} className="mb-2 opacity-70" />
                        <p className="text-[14px] font-medium">{cfg.label}</p>
                        <p className="mt-0.5 text-[12px] text-low">{cfg.tagline}</p>
                      </button>
                    )
                  })}
                </div>
              </>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

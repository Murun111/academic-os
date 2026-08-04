// First-launch stage question + reopenable stage picker.
// Shows automatically when the profile has no stage yet; afterwards it opens
// from the Sidebar stage pill. One question, four cards, no other setup.
import { AnimatePresence, motion } from 'framer-motion'
import { GraduationCap, BookOpen, FlaskConical, Rocket } from 'lucide-react'
import { useOs } from '../lib/store'
import { STAGES, STAGE_ORDER, type Stage } from '../lib/stageConfig'

const ICONS: Record<Stage, typeof GraduationCap> = {
  highschool: GraduationCap,
  undergrad: BookOpen,
  grad: FlaskConical,
  beyond: Rocket,
}

export function StageSetup() {
  const stage = useOs((s) => s.stage)
  const stageLoaded = useOs((s) => s.stageLoaded)
  const pickerOpen = useOs((s) => s.stagePickerOpen)
  const setStage = useOs((s) => s.setStage)
  const openPicker = useOs((s) => s.openStagePicker)

  const firstRun = stageLoaded && stage === null
  const open = firstRun || pickerOpen

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          transition={{ duration: 0.16 }}
          onMouseDown={(e) => {
            // first run must answer; reopened picker can be dismissed
            if (!firstRun && e.target === e.currentTarget) openPicker(false)
          }}
          role="dialog"
          aria-modal="true"
          aria-label="Choose your stage"
        >
          <motion.div
            className="glass-strong w-[520px] rounded-[18px] p-6"
            initial={{ opacity: 0, y: 10, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.99 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
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
                    onClick={() => void setStage(key)}
                    className={`rounded-[12px] border p-4 text-left transition-colors duration-150 ${
                      active
                        ? 'border-black/25 bg-black/6'
                        : 'border-line hover:border-black/15 hover:bg-black/4'
                    }`}
                  >
                    <Icon size={18} strokeWidth={1.75} className="mb-2 opacity-70" />
                    <p className="text-[14px] font-medium">{cfg.label}</p>
                    <p className="mt-0.5 text-[12px] text-low">{cfg.tagline}</p>
                  </button>
                )
              })}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

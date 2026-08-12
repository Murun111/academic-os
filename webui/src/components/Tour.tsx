// First-run guided tour — a spotlight walkthrough over the real UI.
// Navigates between pages, highlights actual elements ([data-tour] anchors),
// and explains how to use each one. Auto-starts after onboarding (once),
// replayable from Settings.
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { useOs } from '../lib/store'

export const TOUR_DONE_KEY = 'academicos.tourDone'

interface TourStep {
  route?: string // navigate here before showing the step
  target?: string // CSS selector to spotlight; omitted → centered card
  title: string
  body: string
}

const STEPS: TourStep[] = [
  {
    route: '/',
    title: 'Welcome to Academic OS',
    body: 'A two-minute walkthrough of how everything works. One thing first: this app runs entirely on your computer — your applications, grades, and essays are never uploaded anywhere.',
  },
  {
    target: '[data-tour="nav"]',
    title: 'Your rooms',
    body: 'Everything lives in these pages. Dashboard is the overview; the pipeline (Colleges / Programs) tracks applications; Study plans your week; Courses holds classes and grades; Documents keeps essay versions; Assistants and Approvals run the automation.',
  },
  {
    target: '[data-tour="stage-pill"]',
    title: 'Your stage',
    body: "This is where you said you are — high school, undergrad, gap year, grad, or beyond. It shapes the whole app: page names, which checklists you get, what shows first. Click it anytime to change.",
  },
  {
    route: '/applications',
    target: '[data-tour="apps-add"]',
    title: 'Add your applications',
    body: 'One card per college, scholarship, or program. Every new card auto-fills a checklist of what that kind of application actually needs — essays, letters, transcripts — so nothing gets forgotten.',
  },
  {
    target: '[data-tour="apps-scout"]',
    title: 'Let the scout hunt for you',
    body: 'Pick a few chips about yourself and the scout searches trusted scholarship sites on the real web. Anything it finds becomes a proposal in Approvals — nothing enters your pipeline unless you approve it.',
  },
  {
    target: '[data-tour="apps-board"]',
    title: 'Drag cards forward',
    body: 'The board runs Researching → Preparing → Submitted → Interview → Decision. Drag cards between columns as you make progress. Click any card to open it: checklist, description, deadline, fees and award amounts.',
  },
  {
    route: '/study',
    target: '[data-tour="study-quickadd"]',
    title: 'Plan your week',
    body: 'Type a task, pick a day, hit Add. Application deadlines and course due dates appear here automatically alongside your own tasks.',
  },
  {
    target: '[data-tour="study-week"]',
    title: 'The week at a glance',
    body: 'All seven days, no scrolling. The dots tell you what each item is — amber for application deadlines, green for assignments, gray for your tasks. Check tasks off right here.',
  },
  {
    route: '/approvals',
    target: 'main h1',
    title: 'You approve everything',
    body: 'Assistants never act on their own. When the scout finds a scholarship or any assistant wants to change your data, the request waits here for your yes or no.',
  },
  {
    route: '/settings',
    target: '[data-tour="settings-ai"]',
    title: 'Private AI, one download',
    body: 'Download the model once and essay feedback + AI briefings run fully on this computer — offline, no account, nothing sent anywhere.',
  },
  {
    target: '[data-tour="settings-reminders"]',
    title: 'Deadline reminders',
    body: 'Once a day while the app is open, a Mac notification sums up everything due in the next 7 days. Test it here, or turn it off.',
  },
  {
    target: '[data-tour="settings-memory"]',
    title: 'You control what it remembers',
    body: 'Chats leave behind small notes the app recalls later. See every one of them here, delete any of them, or wipe the lot. Your data folder is yours — back it up by copying it.',
  },
  {
    route: '/',
    title: "That's the tour",
    body: 'The "start here" checklist on the Dashboard walks you through setup: add your first application, add courses or connect Canvas. Replay this tour anytime from Settings.',
  },
]

const PAD = 6 // spotlight padding around the target
const CARD_W = 340

export function Tour() {
  const open = useOs((s) => s.tourOpen)
  const setTour = useOs((s) => s.setTour)
  const navigate = useNavigate()
  const [i, setI] = useState(0)
  const [rect, setRect] = useState<DOMRect | null>(null)
  const [ready, setReady] = useState(false)
  const cancelRef = useRef(false)

  useEffect(() => {
    if (open) { setI(0) }
  }, [open])

  const step = STEPS[i]

  // On step change: navigate if needed, then find + measure the target.
  useEffect(() => {
    if (!open) return
    cancelRef.current = false
    setReady(false)
    const run = async () => {
      if (step.route) navigate(step.route)
      const deadline = Date.now() + 3500
      while (!cancelRef.current && Date.now() < deadline) {
        const el = step.target ? document.querySelector(step.target) : null
        if (!step.target) break
        if (el) {
          el.scrollIntoView({ block: 'center' })
          await new Promise((r) => setTimeout(r, 320)) // let transition + scroll settle
          if (cancelRef.current) return
          setRect(el.getBoundingClientRect())
          setReady(true)
          return
        }
        await new Promise((r) => setTimeout(r, 120))
      }
      if (!cancelRef.current) {
        setRect(null) // centered fallback
        setReady(true)
      }
    }
    void run()
    return () => { cancelRef.current = true }
  }, [open, i]) // eslint-disable-line react-hooks/exhaustive-deps

  // keep the spotlight glued to the target through scrolls and resizes
  useEffect(() => {
    if (!open || !ready || !step.target) return
    const update = () => {
      const el = document.querySelector(step.target!)
      if (el) setRect(el.getBoundingClientRect())
    }
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    return () => {
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update, true)
    }
  }, [open, ready, i]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!open || !ready) return null

  const finish = () => {
    localStorage.setItem(TOUR_DONE_KEY, '1')
    setTour(false)
    navigate('/')
  }

  const next = () => (i < STEPS.length - 1 ? setI(i + 1) : finish())
  const back = () => i > 0 && setI(i - 1)

  // tooltip position: below the spotlight when it fits, else above; when the
  // target is too tall for either, pin to the bottom edge — never off-screen
  let cardStyle: CSSProperties
  if (rect) {
    const CARD_H = 250 // generous estimate; the card also gets a max-height
    let top: number
    if (rect.bottom + PAD + 12 + CARD_H + 16 <= window.innerHeight) {
      top = rect.bottom + PAD + 12 // below
    } else if (rect.top - PAD - 12 - CARD_H >= 16) {
      top = rect.top - PAD - 12 - CARD_H // above
    } else {
      top = window.innerHeight - CARD_H - 16 // pinned to the bottom edge
    }
    const left = Math.min(Math.max(16, rect.left), window.innerWidth - CARD_W - 16)
    cardStyle = { position: 'fixed', top, left, width: CARD_W, maxHeight: CARD_H }
  } else {
    cardStyle = {
      position: 'fixed', top: '50%', left: '50%',
      transform: 'translate(-50%, -50%)', width: CARD_W,
    }
  }

  return (
    <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true" aria-label="Tutorial">
      {/* click shield */}
      <div className="absolute inset-0" onClick={next} />
      {/* spotlight (its huge shadow darkens everything else) */}
      {rect ? (
        <div
          className="pointer-events-none fixed rounded-[14px] transition-all duration-300"
          style={{
            top: rect.top - PAD, left: rect.left - PAD,
            width: rect.width + PAD * 2, height: rect.height + PAD * 2,
            boxShadow: '0 0 0 9999px rgba(20, 18, 12, 0.52)',
          }}
        />
      ) : (
        <div className="pointer-events-none fixed inset-0 bg-black/52" />
      )}

      <div style={cardStyle} className="glass-strong overflow-y-auto rounded-[16px] p-5" onClick={(e) => e.stopPropagation()}>
        <p className="label-mono mb-1.5">{i + 1} / {STEPS.length}</p>
        <h2 className="mb-1.5 text-[16px] font-semibold tracking-[-0.01em]">{step.title}</h2>
        <p className="mb-4 text-[13px] leading-relaxed text-mid">{step.body}</p>
        <div className="flex items-center justify-between">
          <button onClick={finish} className="text-[12.5px] text-low hover:text-mid">
            Skip tour
          </button>
          <div className="flex items-center gap-2">
            {i > 0 && (
              <button onClick={back} className="rounded-lg px-3 py-1.5 text-[13px] text-mid hover:bg-ink/5 hover:text-hi">
                Back
              </button>
            )}
            <button onClick={next} className="rounded-lg bg-ink/8 px-3.5 py-1.5 text-[13px] text-hi hover:bg-ink/12">
              {i === STEPS.length - 1 ? 'Done' : 'Next'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

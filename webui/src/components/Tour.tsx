// First-run guided tour: a spotlight walkthrough over the real UI.
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
    body: 'A two-minute walkthrough: plan your classes, study, then apply. This app runs on your computer. Your applications, grades, and essays are never uploaded anywhere.',
  },
  {
    target: '[data-tour="nav"]',
    title: 'Your rooms',
    body: 'Courses and Study plan your term. Learning is where you practice. Colleges or Programs track applications. Documents keeps essays and resumes. Approvals is where you say yes or no.',
  },
  {
    target: '[data-tour="stage-pill"]',
    title: 'Your stage',
    body: 'This is where you said you are: high school, undergrad, gap year, grad, or beyond. It changes page names, checklists, and what shows first. Click it anytime to change.',
  },
  {
    route: '/courses',
    target: '[data-tour="courses-add"]',
    title: 'Classes and grades',
    body: 'Add classes by hand, or connect Canvas in Settings to sync courses, assignments, and grades. Open a class to set credits and see what you need on the final.',
  },
  {
    target: '[data-tour="courses-syllabus"]',
    title: 'Import a syllabus',
    body: 'Upload or paste a syllabus and the local AI pulls out assignments and due dates. You see the list first and choose what to add.',
  },
  {
    route: '/study',
    target: '[data-tour="study-quickadd"]',
    title: 'Plan your week',
    body: 'Type a task, pick a day, hit Add. Application deadlines and course due dates show up here on their own, next to your tasks.',
  },
  {
    target: '[data-tour="study-week"]',
    title: 'The week at a glance',
    body: 'All seven days in one view. Amber is application deadlines, green is assignments, gray is your tasks. Check tasks off right here.',
  },
  {
    route: '/calendar',
    target: '[data-tour="calendar-grid"]',
    title: 'The whole month',
    body: 'Everything with a date lands on this grid. Click any item to jump to its card.',
  },
  {
    route: '/learning?tab=review',
    target: '[data-tour="learning-tabs"]',
    title: 'Learn what you study',
    body: 'Review shows the flashcards due today. Rate each one and the app picks when you see it again. The other tabs hold quizzes, guides, mastery, a focus timer, and the AI tutor.',
  },
  {
    route: '/learning?tab=decks',
    target: '[data-tour="learning-import"]',
    title: 'Bring your flashcards',
    body: 'Decks hold your cards. Already have some? Import an Anki file or paste a Quizlet set instead of retyping.',
  },
  {
    route: '/learning?tab=generate',
    target: '[data-tour="learning-generate"]',
    title: 'Generate study material',
    body: 'Type a topic or paste your notes, and the local AI drafts flashcards, a quiz, or a study guide. It can make mistakes, so read what it makes before you rely on it.',
  },
  {
    route: '/applications',
    target: '[data-tour="apps-add"]',
    title: 'Add your applications',
    body: 'One card per college, scholarship, or program. Each new card fills in a checklist of what that kind of application needs, like essays, letters, and transcripts.',
  },
  {
    target: '[data-tour="apps-scout"]',
    title: 'Let the scout look for you',
    body: 'Pick a few chips about yourself and the scout searches trusted scholarship sites. Anything it finds waits in Approvals. Nothing joins your list unless you approve it.',
  },
  {
    target: '[data-tour="apps-import-csv"]',
    title: 'Import scholarships from a CSV',
    body: 'Keep a scholarship spreadsheet already? Save it as CSV and import it here. You can preview it first, so you see what will be added.',
  },
  {
    title: 'Move cards forward',
    body: 'Once you add applications, they show up on a board: Researching, Preparing, Submitted, Interview, Decision. Drag cards as you go. Click one to open its checklist. Archive it when you are done.',
  },
  {
    route: '/documents',
    target: '[data-tour="docs-add"]',
    title: 'Essays and resumes',
    body: 'Drafts save on their own and stay on this computer. Starting a CV? Pick a resume template. The essay coach and resume coach tell you what to fix first.',
  },
  {
    route: '/approvals',
    target: 'main h1',
    title: 'You approve everything',
    body: 'Assistants never act on their own. When the scout finds a scholarship or an assistant wants to change your data, the request waits here for your yes or no.',
  },
  {
    route: '/settings',
    target: '[data-tour="settings-ai"]',
    title: 'Private AI, one download',
    body: 'Download the model once. Essay and resume feedback, the tutor, and Generate then run on this computer, offline, with no account.',
  },
  {
    target: '[data-tour="settings-reminders"]',
    title: 'Deadline reminders',
    body: 'Once a day while the app is open, a notification lists what is due in the next 7 days. Test it here, or turn it off.',
  },
  {
    target: '[data-tour="settings-memory"]',
    title: 'You control what it remembers',
    body: 'Chats leave small notes the app recalls later. See every one here, delete any of them, or wipe them all.',
  },
  {
    route: '/',
    title: "That's the tour",
    body: 'Start with the checklist on the Dashboard. Press Cmd+K (Ctrl+K on Windows) anywhere to jump to a college, class, or essay. Replay this tour anytime from Settings.',
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
  const nextRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (open) { setI(0) }
  }, [open])

  // Focus: remember what had focus when the tour opened and give it back on close.
  useEffect(() => {
    if (!open) return
    const prev = document.activeElement as HTMLElement | null
    return () => prev?.focus?.()
  }, [open])

  // Each step lands focus on Next, so Enter/Space advances and screen readers
  // start at the card.
  useEffect(() => {
    if (open && ready) nextRef.current?.focus()
  }, [open, ready, i])

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
          // re-query: the first match may be an outgoing page's element
          const fresh = document.querySelector(step.target)
          const r = fresh?.getBoundingClientRect()
          if (!fresh || !fresh.isConnected || !r || r.width < 2 || r.height < 2) continue
          setRect(r)
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

  const finish = () => {
    // blocked site data makes setItem throw: the overlay must still close
    try { localStorage.setItem(TOUR_DONE_KEY, '1') } catch { /* storage unavailable */ }
    setTour(false)
    navigate('/')
  }

  const next = () => (i < STEPS.length - 1 ? setI(i + 1) : finish())
  const back = () => i > 0 && setI(i - 1)

  // Escape closes; arrow keys step.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); finish() }
      else if (e.key === 'ArrowRight') { e.preventDefault(); next() }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); back() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (!open || !ready) return null


  // tooltip position: below the spotlight when it fits, else above; when the
  // target is too tall for either, pin to the bottom edge. Never off-screen
  let cardStyle: CSSProperties = {}
  if (rect) {
    const CARD_H = 300 // generous estimate; the card also gets a max-height
    let top: number
    // Tall target hugging the left edge (the sidebar): sit beside it instead
    // of pinning over the items the step describes.
    const besideLeft = rect.height > window.innerHeight * 0.5
      && rect.right + PAD + 12 + CARD_W + 16 <= window.innerWidth
      && rect.left < window.innerWidth / 3
    if (besideLeft) {
      top = Math.min(Math.max(16, rect.top), window.innerHeight - CARD_H - 16)
      cardStyle = { position: 'fixed', top, left: rect.right + PAD + 12, width: CARD_W, maxHeight: CARD_H }
    } else if (rect.bottom + PAD + 12 + CARD_H + 16 <= window.innerHeight) {
      top = rect.bottom + PAD + 12 // below
    } else if (rect.top - PAD - 12 - CARD_H >= 16) {
      top = rect.top - PAD - 12 - CARD_H // above
    } else {
      top = window.innerHeight - CARD_H - 16 // pinned to the bottom edge
    }
    if (!besideLeft) {
      const left = Math.min(Math.max(16, rect.left), window.innerWidth - CARD_W - 16)
      cardStyle = { position: 'fixed', top, left, width: CARD_W, maxHeight: CARD_H }
    }
  } else {
    cardStyle = {
      position: 'fixed', top: '50%', left: '50%',
      transform: 'translate(-50%, -50%)', width: CARD_W,
    }
  }

  return (
    <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true" aria-label="Tutorial">
      {/* click shield */}
      <div className="absolute inset-0" onClick={next} aria-hidden="true" />
      {/* spotlight (its huge shadow darkens everything else) */}
      {rect ? (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed rounded-[14px] transition-all duration-300 motion-reduce:transition-none"
          style={{
            top: rect.top - PAD, left: rect.left - PAD,
            width: rect.width + PAD * 2, height: rect.height + PAD * 2,
            boxShadow: '0 0 0 9999px rgba(20, 18, 12, 0.52)',
          }}
        />
      ) : (
        <div aria-hidden="true" className="pointer-events-none fixed inset-0 bg-black/52" />
      )}

      <div style={cardStyle} className="glass-strong overflow-y-auto rounded-[16px] p-5" onClick={(e) => e.stopPropagation()}>
        <div aria-live="polite" aria-atomic="true">
          <p className="label-mono mb-1.5">{i + 1} / {STEPS.length}</p>
          <h2 className="mb-1.5 text-[16px] font-semibold tracking-[-0.01em]">{step.title}</h2>
          <p className="mb-4 text-[13px] leading-relaxed text-mid">{step.body}</p>
        </div>
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
            <button ref={nextRef} onClick={next} className="rounded-lg bg-ink/8 px-3.5 py-1.5 text-[13px] text-hi hover:bg-ink/12">
              {i === STEPS.length - 1 ? 'Done' : 'Next'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

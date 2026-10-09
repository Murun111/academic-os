import { create } from 'zustand'
import { api } from './api'
import { profileApi } from './profileApi'
import type { Stage } from './stageConfig'
import type { Track } from './trackConfig'
import type { AgentInfo, Approval, Health, OsEvent, Run } from './types'

export interface Toast {
  id: string
  text: string
  to?: string
}

interface OsStore {
  agents: AgentInfo[]
  runs: Run[]
  approvals: Approval[]
  events: OsEvent[]
  health: Health | null
  toasts: Toast[]
  paletteOpen: boolean
  booted: boolean
  stage: Stage | null
  stageLoaded: boolean
  stagePickerOpen: boolean
  userName: string
  track: Track | null
  testDate: string
  reminders: boolean
  tourOpen: boolean
  setTour: (open: boolean) => void
  theme: ThemePref
  setTheme: (theme: ThemePref) => void
  boot: () => void
  // setters resolve false (after rolling state back + toasting) when the save failed
  setStage: (stage: Stage) => Promise<boolean>
  setUserName: (name: string) => Promise<boolean>
  setTrack: (track: Track | null) => Promise<boolean>
  setTestDate: (testDate: string) => Promise<boolean>
  setReminders: (reminders: boolean) => Promise<boolean>
  openStagePicker: (open: boolean) => void
  setPalette: (open: boolean) => void
  dismissToast: (id: string) => void
  runAgent: (name: string) => Promise<void>
  decide: (id: string, approve: boolean) => Promise<void>
}

const MAX_EVENTS = 200
let unsubscribe: (() => void) | null = null

const THEME_KEY = 'academicos.theme'

export type ThemePref = 'system' | 'light' | 'dark'

const _mq = window.matchMedia('(prefers-color-scheme: dark)')

function applyTheme(pref: ThemePref) {
  const resolved = pref === 'system' ? (_mq.matches ? 'dark' : 'light') : pref
  const root = document.documentElement
  if (root.dataset.theme === resolved) return
  // Flip every color in one frame: without this, elements with
  // transition-colors fade while the rest snap, which reads as a glitch.
  root.classList.add('theme-switching')
  root.dataset.theme = resolved
  document.querySelector('meta[name="color-scheme"]')?.setAttribute('content', resolved)
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove('theme-switching')))
}

function readPref(): ThemePref {
  try {
    const saved = localStorage.getItem(THEME_KEY)
    return saved === 'dark' || saved === 'light' ? saved : 'system'
  } catch {
    return 'system'
  }
}

function initialTheme(): ThemePref {
  const pref = readPref()
  applyTheme(pref)
  return pref
}

function pushToast(
  set: (fn: (s: OsStore) => Partial<OsStore>) => void,
  get: () => OsStore,
  text: string,
) {
  const toast: Toast = { id: `err_${Date.now()}`, text }
  set((s) => ({ toasts: [...s.toasts, toast].slice(-3) }))
  setTimeout(() => get().dismissToast(toast.id), 6000)
}

export const useOs = create<OsStore>((set, get) => ({
  agents: [],
  runs: [],
  approvals: [],
  events: [],
  health: null,
  toasts: [],
  paletteOpen: false,
  booted: false,
  stage: null,
  stageLoaded: false,
  stagePickerOpen: false,
  userName: '',
  track: null,
  testDate: '',
  reminders: true,
  tourOpen: false,
  theme: initialTheme(),

  setTour: (tourOpen) => set({ tourOpen }),

  setTheme: (theme) => {
    try { localStorage.setItem(THEME_KEY, theme) } catch { /* private mode: applies for this session */ }
    applyTheme(theme)
    set({ theme })
  },

  boot: () => {
    if (get().booted) return
    set({ booted: true })
    // A failed read (backend still starting, 5xx) is NOT "first run": keep
    // stageLoaded false and retry, otherwise the unskippable onboarding modal
    // opens for an existing user and picking a stage overwrites their profile.
    let profileTries = 0
    const loadProfile = () => {
      void profileApi.get().then((p) => {
        if (p) {
          set({ stage: p.stage, userName: p.name, track: p.track, testDate: p.test_date, reminders: p.reminders, stageLoaded: true })
        } else {
          profileTries += 1
          setTimeout(loadProfile, Math.min(1000 * profileTries, 5000))
        }
      })
    }
    loadProfile()
    void api.agents().then((agents) => set({ agents }))
    void api.runs().then((runs) => set({ runs }))
    void api.approvals().then((approvals) => set({ approvals }))
    void api.health().then((health) => set({ health }))
    void api.seedEvents().then((seed) =>
      set((s) => ({ events: [...s.events, ...seed].slice(0, MAX_EVENTS) })),
    )
    unsubscribe?.()
    unsubscribe = api.events((e) => {
      set((s) => ({ events: [e, ...s.events].slice(0, MAX_EVENTS) }))
      // an agent started/finished: refresh cards + recent runs so "Running…" never sticks
      if (e.kind === 'agent' && /\b(started|finished)$/.test(e.message)) {
        void api.agents().then((agents) => set({ agents }))
        void api.runs().then((runs) => set({ runs }))
      }
      // a live escalation refreshes the queue and surfaces a toast
      if (e.kind === 'approval' && e.message.includes('escalated')) {
        void api.approvals().then((approvals) => set({ approvals }))
        const toast: Toast = { id: e.id, text: e.message, to: '/approvals' }
        set((s) => ({ toasts: [...s.toasts, toast].slice(-3) }))
        setTimeout(() => get().dismissToast(toast.id), 6000)
      }
    })
  },

  // the backend PUT replaces the whole profile — every setter sends every field.
  // Optimistic: on a failed PUT (409 newer data, 422 bad date, backend down)
  // roll back to the previous values and tell the user.
  setStage: async (stage) => {
    const prev = get().stage
    set({ stage, stagePickerOpen: false })
    const s = get()
    const ok = await profileApi.set(stage, s.userName, s.track, s.testDate, s.reminders)
    if (!ok) { set({ stage: prev }); pushToast(set, get, 'Could not save your stage. Nothing was changed.') }
    return ok
  },

  setUserName: async (userName) => {
    const prev = get().userName
    set({ userName })
    const s = get()
    if (!s.stage) return true
    const ok = await profileApi.set(s.stage, userName, s.track, s.testDate, s.reminders)
    if (!ok) { set({ userName: prev }); pushToast(set, get, 'Could not save your name. Nothing was changed.') }
    return ok
  },

  setTrack: async (track) => {
    const prev = get().track
    set({ track })
    const s = get()
    if (!s.stage) return true
    const ok = await profileApi.set(s.stage, s.userName, track, s.testDate, s.reminders)
    if (!ok) { set({ track: prev }); pushToast(set, get, 'Could not save that. Nothing was changed.') }
    return ok
  },

  setTestDate: async (testDate) => {
    const prev = get().testDate
    set({ testDate })
    const s = get()
    if (!s.stage) return true
    const ok = await profileApi.set(s.stage, s.userName, s.track, testDate, s.reminders)
    if (!ok) { set({ testDate: prev }); pushToast(set, get, 'Could not save that date. Nothing was changed.') }
    return ok
  },

  setReminders: async (reminders) => {
    const prev = get().reminders
    set({ reminders })
    const s = get()
    if (!s.stage) return true
    const ok = await profileApi.set(s.stage, s.userName, s.track, s.testDate, reminders)
    if (!ok) { set({ reminders: prev }); pushToast(set, get, 'Could not save that setting. Nothing was changed.') }
    return ok
  },

  openStagePicker: (stagePickerOpen) => set({ stagePickerOpen }),

  setPalette: (paletteOpen) => set({ paletteOpen }),

  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  runAgent: async (name) => {
    try {
      await api.runAgent(name)
    } catch (err) {
      // disabled agent, unknown name, backend down: tell the user instead of an unhandled rejection
      const toast: Toast = { id: `run_err_${Date.now()}`, text: `Could not run ${name}: ${err instanceof Error ? err.message : String(err)}` }
      set((s) => ({ toasts: [...s.toasts, toast].slice(-3) }))
      setTimeout(() => get().dismissToast(toast.id), 6000)
      return
    }
    set({ agents: await api.agents() })
    set((s) => ({
      events: [
        { id: `local_${Date.now()}`, t: new Date().toISOString(), kind: 'agent' as const, agent: name, message: `run requested → 202 running` },
        ...s.events,
      ].slice(0, MAX_EVENTS),
    }))
  },

  decide: async (id, approve) => {
    const item = get().approvals.find((a) => a.id === id)
    const failure = await api.decide(id, approve)
    set({ approvals: await api.approvals() })
    if (failure) {
      const toast: Toast = { id: `decide_err_${Date.now()}`, text: failure }
      set((s) => ({ toasts: [...s.toasts, toast].slice(-3) }))
      setTimeout(() => get().dismissToast(toast.id), 8000)
    }
    if (item) {
      set((s) => ({
        events: [
          { id: `local_${Date.now()}`, t: new Date().toISOString(), kind: 'approval' as const, agent: item.agent, message: `${item.tool} ${approve ? 'approved' : 'denied'}` },
          ...s.events,
        ].slice(0, MAX_EVENTS),
      }))
    }
  },
}))

// dev-only introspection handle (used by preview tooling; stripped in prod)
if (import.meta.env.DEV) {
  ;(window as unknown as Record<string, unknown>).__os = useOs
}

// Follow the OS live. Changing the Mac's appearance is the newest signal of
// what the user wants, so it also clears an explicit Light/Dark pick and puts
// the app back on System.
_mq.addEventListener('change', () => {
  if (useOs.getState().theme !== 'system') useOs.getState().setTheme('system')
  else applyTheme('system')
})

// Keep other open tabs of the app in step with a change made in this one.
window.addEventListener('storage', (e) => {
  if (e.key !== THEME_KEY) return
  const pref = readPref()
  applyTheme(pref)
  useOs.setState({ theme: pref })
})

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
  setStage: (stage: Stage) => Promise<void>
  setUserName: (name: string) => Promise<void>
  setTrack: (track: Track | null) => Promise<void>
  setTestDate: (testDate: string) => Promise<void>
  setReminders: (reminders: boolean) => Promise<void>
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
  document.documentElement.dataset.theme = resolved
  document.querySelector('meta[name="color-scheme"]')?.setAttribute('content', resolved)
}

function initialTheme(): ThemePref {
  const saved = localStorage.getItem(THEME_KEY)
  const pref: ThemePref = saved === 'dark' || saved === 'light' ? saved : 'system'
  applyTheme(pref)
  return pref
}

// follow the OS live: when macOS flips appearance and the pref is "system",
// restyle immediately — no reload needed
_mq.addEventListener('change', () => {
  if ((localStorage.getItem(THEME_KEY) ?? 'system') === 'system') applyTheme('system')
})

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
    localStorage.setItem(THEME_KEY, theme)
    applyTheme(theme)
    set({ theme })
  },

  boot: () => {
    if (get().booted) return
    set({ booted: true })
    void profileApi.get().then((p) =>
      set({ stage: p.stage, userName: p.name, track: p.track, testDate: p.test_date, reminders: p.reminders, stageLoaded: true }),
    )
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
      // a live escalation refreshes the queue and surfaces a toast
      if (e.kind === 'approval' && e.message.includes('escalated')) {
        void api.approvals().then((approvals) => set({ approvals }))
        const toast: Toast = { id: e.id, text: e.message, to: '/approvals' }
        set((s) => ({ toasts: [...s.toasts, toast].slice(-3) }))
        setTimeout(() => get().dismissToast(toast.id), 6000)
      }
    })
  },

  // the backend PUT replaces the whole profile — every setter sends every field
  setStage: async (stage) => {
    set({ stage, stagePickerOpen: false })
    const s = get()
    await profileApi.set(stage, s.userName, s.track, s.testDate, s.reminders)
  },

  setUserName: async (userName) => {
    set({ userName })
    const s = get()
    if (s.stage) await profileApi.set(s.stage, userName, s.track, s.testDate, s.reminders)
  },

  setTrack: async (track) => {
    set({ track })
    const s = get()
    if (s.stage) await profileApi.set(s.stage, s.userName, track, s.testDate, s.reminders)
  },

  setTestDate: async (testDate) => {
    set({ testDate })
    const s = get()
    if (s.stage) await profileApi.set(s.stage, s.userName, s.track, testDate, s.reminders)
  },

  setReminders: async (reminders) => {
    set({ reminders })
    const s = get()
    if (s.stage) await profileApi.set(s.stage, s.userName, s.track, s.testDate, reminders)
  },

  openStagePicker: (stagePickerOpen) => set({ stagePickerOpen }),

  setPalette: (paletteOpen) => set({ paletteOpen }),

  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  runAgent: async (name) => {
    await api.runAgent(name)
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
    await api.decide(id, approve)
    set({ approvals: await api.approvals() })
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

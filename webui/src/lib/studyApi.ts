// Study / Task Planner client — talks to /api/study/* on the Academic OS
// backend (same-origin). Every call degrades to a safe empty default so
// the page stays calm if the backend or a cross-module lookup is down.

export const TASK_PRIORITIES = ['low', 'normal', 'high'] as const
export type TaskPriority = (typeof TASK_PRIORITIES)[number]

export interface Task {
  id: string
  title: string
  created_at: string
  day: string | null
  due: string | null
  done: boolean
  priority: TaskPriority
  notes: string
}

export type AgendaKind = 'task' | 'application' | 'assignment'

export interface AgendaItem {
  kind: AgendaKind
  id: string | null
  title: string | null
  date: string | null
  meta: Record<string, unknown>
}

export interface Agenda {
  items: AgendaItem[]
  count: number
}

export interface TaskCreate {
  title: string
  day?: string | null
  due?: string | null
  priority?: TaskPriority
  notes?: string
}

export interface TaskUpdate {
  title?: string
  day?: string | null
  due?: string | null
  done?: boolean
  priority?: TaskPriority
  notes?: string
}

async function sget<T>(path: string, fallback: T): Promise<T> {
  try {
    const r = await fetch(`/api/study${path}`)
    if (!r.ok) return fallback
    return (await r.json()) as T
  } catch {
    return fallback
  }
}

async function spost<T>(path: string, body?: unknown): Promise<T | null> {
  try {
    const r = await fetch(`/api/study${path}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    if (!r.ok) return null
    return (await r.json()) as T
  } catch {
    return null
  }
}

async function spatch<T>(path: string, body: unknown): Promise<T | null> {
  try {
    const r = await fetch(`/api/study${path}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r.ok) return null
    return (await r.json()) as T
  } catch {
    return null
  }
}

async function sdel(path: string): Promise<boolean> {
  try {
    const r = await fetch(`/api/study${path}`, { method: 'DELETE' })
    return r.ok
  } catch {
    return false
  }
}

export const study = {
  agenda: (days = 7) => sget<Agenda>(`/agenda?days=${days}`, { items: [], count: 0 }),
  tasks: (params?: { day?: string; done?: boolean }) => {
    const q = new URLSearchParams()
    if (params?.day) q.set('day', params.day)
    if (params?.done !== undefined) q.set('done', String(params.done))
    const qs = q.toString()
    return sget<Task[]>(`/tasks${qs ? `?${qs}` : ''}`, [])
  },
  addTask: (task: TaskCreate) => spost<Task>('/tasks', task),
  updateTask: (id: string, patch: TaskUpdate) => spatch<Task>(`/tasks/${id}`, patch),
  deleteTask: (id: string) => sdel(`/tasks/${id}`),
  markDone: (id: string) => spost<Task>(`/tasks/${id}/done`),
  reopen: (id: string) => spost<Task>(`/tasks/${id}/reopen`),
}

// kind → status tone, matching the shared ui.tsx state palette
export function kindTone(kind: AgendaKind): string {
  if (kind === 'application') return 'pending' // loudest — deadlines that matter most
  if (kind === 'assignment') return 'medium'
  return ''
}

export function isOverdue(dateStr: string | null): boolean {
  if (!dateStr) return false
  const today = new Date().toISOString().slice(0, 10)
  return dateStr < today
}

export function isToday(dateStr: string | null): boolean {
  if (!dateStr) return false
  return dateStr === new Date().toISOString().slice(0, 10)
}

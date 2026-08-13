// Applications Pipeline client — talks to backend/routers/applications.py
// (/api/applications/*) on the same origin. Self-contained: this file owns
// its own types and fetch helpers, independent of ../lib/api.ts. Every call
// degrades to a safe fallback so the page stays calm if the backend is down.

export const APPLICATION_TYPES = ['undergrad', 'grad', 'scholarship', 'exchange'] as const
export type ApplicationType = (typeof APPLICATION_TYPES)[number]

// pipeline order — the kanban board reads columns off this array
export const APPLICATION_STATUSES = [
  'researching', 'preparing', 'submitted', 'secondaries', 'interview', 'decision',
] as const
export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number]

export const DECISION_RESULTS = ['', 'accepted', 'rejected', 'waitlisted'] as const
export type DecisionResult = (typeof DECISION_RESULTS)[number]

export interface Requirement {
  id: string
  label: string
  done: boolean
}

export interface Application {
  id: string
  name: string
  org: string
  type: ApplicationType
  status: ApplicationStatus
  decision_result: DecisionResult
  deadline: string | null
  url: string
  notes: string
  requirements: Requirement[]
  document_ids: string[]
  amount: number | null
  app_fee: number | null
  fee_waived: boolean
  archived: boolean
  created_at: string
  updated_at: string
}

export interface ApplicationCreateInput {
  name: string
  type: ApplicationType
  org?: string
  deadline?: string | null
  url?: string
  notes?: string
  amount?: number | null
  app_fee?: number | null
  fee_waived?: boolean
}

export interface ApplicationUpdateInput {
  name?: string
  org?: string
  type?: ApplicationType
  status?: ApplicationStatus
  decision_result?: DecisionResult
  deadline?: string | null
  url?: string
  notes?: string
  amount?: number | null
  app_fee?: number | null
  fee_waived?: boolean
  archived?: boolean
}

export interface ApplicationCosts {
  fees_due: number
  fees_waived: number
  potential_awards: number
  won_awards: number
  by_type: Record<string, { count: number; amount: number }>
}

const ZERO_COSTS: ApplicationCosts = {
  fees_due: 0,
  fees_waived: 0,
  potential_awards: 0,
  won_awards: 0,
  by_type: {},
}

async function aget<T>(path: string, fallback: T): Promise<T> {
  try {
    const r = await fetch(`/api/applications${path}`)
    if (!r.ok) return fallback
    return (await r.json()) as T
  } catch {
    return fallback
  }
}

async function amutate<T>(path: string, method: string, body: unknown, fallback: T): Promise<T> {
  try {
    const r = await fetch(`/api/applications${path}`, {
      method,
      headers: { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    if (!r.ok) return fallback
    return (await r.json()) as T
  } catch {
    return fallback
  }
}

interface ItemsReply { items: Application[]; count: number }
interface ItemReply { ok: boolean; item: Application }

export const applicationsApi = {
  list: async (filters?: { type?: string; status?: string }): Promise<Application[]> => {
    const params = new URLSearchParams()
    if (filters?.type) params.set('type', filters.type)
    if (filters?.status) params.set('status', filters.status)
    const qs = params.toString()
    const res = await aget<ItemsReply>(qs ? `?${qs}` : '', { items: [], count: 0 })
    return res.items
  },

  get: (id: string): Promise<Application | null> =>
    aget<{ item: Application | null }>(`/${id}`, { item: null }).then((r) => r.item),

  deadlines: async (days = 30): Promise<Application[]> => {
    const res = await aget<ItemsReply>(`/deadlines?days=${days}`, { items: [], count: 0 })
    return res.items
  },

  costs: (): Promise<ApplicationCosts> => aget<ApplicationCosts>('/costs', ZERO_COSTS),

  create: async (input: ApplicationCreateInput): Promise<Application | null> => {
    const res = await amutate<ItemReply | null>('', 'POST', input, null)
    return res?.item ?? null
  },

  update: async (id: string, input: ApplicationUpdateInput): Promise<Application | null> => {
    const res = await amutate<ItemReply | null>(`/${id}`, 'PATCH', input, null)
    return res?.item ?? null
  },

  remove: async (id: string): Promise<boolean> => {
    const res = await amutate<{ ok: boolean } | null>(`/${id}`, 'DELETE', undefined, null)
    return !!res?.ok
  },

  addRequirement: async (id: string, label: string): Promise<Application | null> => {
    const res = await amutate<ItemReply | null>(`/${id}/requirements`, 'POST', { label }, null)
    return res?.item ?? null
  },

  updateRequirement: async (
    id: string, reqId: string, fields: { label?: string; done?: boolean },
  ): Promise<Application | null> => {
    const res = await amutate<ItemReply | null>(`/${id}/requirements/${reqId}`, 'PATCH', fields, null)
    return res?.item ?? null
  },

  deleteRequirement: async (id: string, reqId: string): Promise<Application | null> => {
    const res = await amutate<ItemReply | null>(`/${id}/requirements/${reqId}`, 'DELETE', undefined, null)
    return res?.item ?? null
  },
}

// deadline urgency → status color bucket, used for the red-toned "due soon" cue
export function deadlineTone(deadline: string | null): string | undefined {
  if (!deadline) return undefined
  const days = Math.ceil((new Date(deadline).getTime() - Date.now()) / 86_400_000)
  if (days < 7) return 'high' // maps to --color-fail via ui.tsx's stateColor
  if (days < 14) return 'medium'
  return undefined
}

export function requirementsProgress(reqs: Requirement[]): string {
  const done = reqs.filter((r) => r.done).length
  return `${done}/${reqs.length}`
}

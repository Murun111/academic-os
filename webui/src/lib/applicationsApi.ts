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
  renewable: boolean
  awarded_amount: number | null
  eligibility: string
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
  renewable?: boolean
  awarded_amount?: number | null
  eligibility?: string
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
  renewable?: boolean
  awarded_amount?: number | null
  eligibility?: string
}

export interface ApplicationCosts {
  fees_due: number
  fees_waived: number
  potential_awards: number
  won_awards: number
  by_type: Record<string, { count: number; amount: number }>
}

export interface ScholarshipSummary {
  count_by_status: Record<string, number>
  potential_total: number
  won_total: number
  won_count: number
  pending_count: number
  next_deadlines: { id: string; name: string; deadline: string; amount: number | null }[]
  essays: { document_id: string; title: string; used_by: { id: string; name: string }[] }[]
}

export interface ScholarshipImportRow {
  row: number
  name: string
  org: string
  amount: number | null
  deadline: string | null
  url: string
  notes: string
  eligibility: string
  renewable: boolean
}

export interface ScholarshipImportResult {
  created: number
  skipped_duplicates: number
  errors: { row: number; message: string }[]
  warnings?: { message: string }[]
  rows?: ScholarshipImportRow[] // present on dry runs only
}

const ZERO_SUMMARY: ScholarshipSummary = {
  count_by_status: {}, potential_total: 0, won_total: 0, won_count: 0,
  pending_count: 0, next_deadlines: [], essays: [],
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

// Like aget/amutate but surfaces failure: null (unreachable) or the server's detail.
async function describeFailure(r: Response): Promise<string> {
  try {
    const j = await r.json()
    if (typeof j?.detail === 'string' && j.detail) return j.detail
  } catch { /* non-JSON body */ }
  return `Request failed (HTTP ${r.status}).`
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

  // Like list(), but distinguishes "backend failed" (null) from "no applications" ([]).
  listChecked: async (): Promise<Application[] | null> => {
    try {
      const r = await fetch('/api/applications')
      if (!r.ok) return null
      return ((await r.json()) as ItemsReply).items
    } catch {
      return null
    }
  },

  get: (id: string): Promise<Application | null> =>
    aget<{ item: Application | null }>(`/${id}`, { item: null }).then((r) => r.item),

  deadlines: async (days = 30): Promise<Application[]> => {
    const res = await aget<ItemsReply>(`/deadlines?days=${days}`, { items: [], count: 0 })
    return res.items
  },

  costs: (): Promise<ApplicationCosts> => aget<ApplicationCosts>('/costs', ZERO_COSTS),

  scholarshipSummary: (): Promise<ScholarshipSummary> =>
    aget<ScholarshipSummary>('/scholarships/summary', ZERO_SUMMARY),

  // Upload a CSV file (or pasted text). Returns {ok:false,error} with the server's detail if the request failed.
  importScholarshipsCsv: async (
    source: File | string, dryRun = false,
  ): Promise<ScholarshipImportResult | { ok: false; error: string }> => {
    try {
      const form = new FormData()
      if (typeof source === 'string') form.set('text', source)
      else form.set('file', source)
      if (dryRun) form.set('dry_run', 'true')
      const r = await fetch('/api/applications/scholarships/import-csv', { method: 'POST', body: form })
      if (!r.ok) {
        let detail = ''
        try { const j = await r.json(); if (typeof j?.detail === 'string') detail = j.detail } catch { /* non-JSON body */ }
        return { ok: false, error: detail || `Import failed (HTTP ${r.status}).` }
      }
      return (await r.json()) as ScholarshipImportResult
    } catch {
      return { ok: false, error: 'Import failed. Is the backend running?' }
    }
  },

  create: async (input: ApplicationCreateInput): Promise<Application | null> => {
    const res = await amutate<ItemReply | null>('', 'POST', input, null)
    return res?.item ?? null
  },

  // Like create(), but reports why it failed so the form can keep the user's input.
  createChecked: async (
    input: ApplicationCreateInput,
  ): Promise<{ item: Application; error?: undefined } | { item: null; error: string }> => {
    try {
      const r = await fetch('/api/applications', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(input),
      })
      if (!r.ok) return { item: null, error: await describeFailure(r) }
      return { item: ((await r.json()) as ItemReply).item }
    } catch {
      return { item: null, error: 'Could not reach the backend. Is it running?' }
    }
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

// Whole calendar days from today (local) to a YYYY-MM-DD deadline. `new Date('YYYY-MM-DD')`
// is UTC midnight, which skews the count by a day around local midnight, so build local dates.
// Returns NaN for anything that is not a valid date.
export function daysUntilDeadline(deadline: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(deadline)
  if (!m) return Number.NaN
  const now = new Date()
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  const due = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return Math.round((due - today) / 86_400_000)
}

// deadline urgency → status color bucket, used for the red-toned "due soon" cue
export function deadlineTone(deadline: string | null): string | undefined {
  if (!deadline) return undefined
  const days = daysUntilDeadline(deadline)
  if (Number.isNaN(days)) return undefined
  if (days < 7) return 'high' // maps to --color-fail via ui.tsx's stateColor
  if (days < 14) return 'medium'
  return undefined
}

export function requirementsProgress(reqs: Requirement[]): string {
  const done = reqs.filter((r) => r.done).length
  return `${done}/${reqs.length}`
}

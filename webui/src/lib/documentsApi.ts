// Documents Hub API client — talks to /api/documents/* on the same origin.
// Self-contained: no imports from other module lib files. Every call
// degrades to a safe empty default so the page stays calm if the backend
// is unreachable.

export const DOCUMENT_KINDS = [
  'essay', 'cv', 'transcript', 'lor', 'certificate', 'other',
] as const
export type DocumentKind = (typeof DOCUMENT_KINDS)[number]

export const DOCUMENT_STATUSES = ['draft', 'in_review', 'final'] as const
export type DocumentStatus = (typeof DOCUMENT_STATUSES)[number]

export interface DocumentHistoryEntry {
  version: number
  note: string
  at: string // ISO datetime
}

export interface Document {
  id: string
  title: string
  kind: DocumentKind
  status: DocumentStatus
  version: number
  history: DocumentHistoryEntry[]
  tags: string[]
  linked_application_ids: string[]
  notes: string
  content: string
  created_at: string
  updated_at: string
}

export interface DocumentListFilters {
  kind?: string
  tag?: string
  application_id?: string
}

async function dget<T>(path: string, fallback: T): Promise<T> {
  try {
    const r = await fetch(`/api/documents${path}`)
    if (!r.ok) return fallback
    return (await r.json()) as T
  } catch {
    return fallback
  }
}

async function dpost<T>(path: string, body?: unknown, method = 'POST'): Promise<T | null> {
  try {
    const r = await fetch(`/api/documents${path}`, {
      method,
      headers: { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    if (!r.ok) return null
    return (await r.json()) as T
  } catch {
    return null
  }
}

function qs(filters: DocumentListFilters = {}): string {
  const params = new URLSearchParams()
  if (filters.kind) params.set('kind', filters.kind)
  if (filters.tag) params.set('tag', filters.tag)
  if (filters.application_id) params.set('application_id', filters.application_id)
  const s = params.toString()
  return s ? `?${s}` : ''
}

export const documentsApi = {
  list: async (filters: DocumentListFilters = {}): Promise<Document[]> => {
    const r = await dget<{ items: Document[]; count: number }>(qs(filters), { items: [], count: 0 })
    return r.items
  },
  get: (id: string) => dget<{ item: Document } | null>(`/${id}`, null),
  add: (body: {
    title: string
    kind: DocumentKind
    status?: DocumentStatus
    tags?: string[]
    linked_application_ids?: string[]
    notes?: string
  }) => dpost<{ ok: boolean; item: Document }>('', body),
  update: (
    id: string,
    body: Partial<Pick<Document, 'title' | 'kind' | 'status' | 'tags' | 'notes' | 'content'>>,
  ) => dpost<{ ok: boolean; item: Document }>(`/${id}`, body, 'PATCH'),
  delete: (id: string) => dpost<{ ok: boolean }>(`/${id}`, undefined, 'DELETE'),
  bumpVersion: (id: string, note: string) =>
    dpost<{ ok: boolean; item: Document }>(`/${id}/versions`, { note }),
  link: (id: string, applicationId: string) =>
    dpost<{ ok: boolean; item: Document }>(`/${id}/link`, { application_id: applicationId }),
  unlink: (id: string, applicationId: string) =>
    dpost<{ ok: boolean; item: Document }>(`/${id}/unlink`, { application_id: applicationId }),
}

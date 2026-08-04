// Agent Routines client — deadline watcher + essay feedback, both on-demand
// endpoints under /api/routines/*. Self-contained: no imports from the shared
// lib/types.ts. Every call degrades to a safe default so the page stays calm
// if the backend or the local model is unreachable.

export interface RoutineCatalogEntry {
  id: string
  name: string
  description: string
  kind: 'on_demand' | string
}

export interface RoutineCatalog {
  routines: RoutineCatalogEntry[]
}

export interface DeadlineDigestItem {
  kind: 'application' | 'assignment' | string
  id: string
  title: string
  due: string | null
  context: string
}

export interface DeadlineDigest {
  items: DeadlineDigestItem[]
  summary: string
}

export interface DeadlineDigestBriefing extends DeadlineDigest {
  briefing: string
  model: string
}

export interface EssayFeedback {
  feedback: string
  model: string
}

export class RoutinesApiError extends Error {
  offline: boolean
  constructor(message: string, offline: boolean) {
    super(message)
    this.offline = offline
  }
}

async function rget<T>(path: string, fallback: T): Promise<T> {
  try {
    const r = await fetch(`/api/routines${path}`)
    if (!r.ok) return fallback
    return (await r.json()) as T
  } catch {
    return fallback
  }
}

// Returns null on 503 (model offline) so callers can show the inline
// "Local model offline" state instead of a generic error.
async function rpostLlm<T>(path: string, body: unknown): Promise<T | null> {
  try {
    const r = await fetch(`/api/routines${path}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r.ok) return null
    return (await r.json()) as T
  } catch {
    return null
  }
}

export const routinesApi = {
  catalog: () => rget<RoutineCatalog>('/catalog', { routines: [] }),
  deadlineDigest: (days = 14) =>
    rget<DeadlineDigest>(`/deadline-digest?days=${days}`, { items: [], summary: '' }),
  deadlineDigestBrief: (days = 14) =>
    rpostLlm<DeadlineDigestBriefing>('/deadline-digest/brief', { days }),
  essayFeedback: (text: string, promptHint = '') =>
    rpostLlm<EssayFeedback>('/essay-feedback', { text, prompt_hint: promptHint }),
}

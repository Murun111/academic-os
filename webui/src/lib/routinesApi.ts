// Agent Routines client — deadline watcher + essay feedback, both on-demand
// endpoints under /api/routines/*. Self-contained: no imports from the shared
// lib/types.ts. The catalog degrades to empty; digest and LLM calls throw so
// pages can tell "nothing there" apart from "it failed".

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

export interface ResumeFeedback {
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

// Throws RoutinesApiError: offline=true for 503 / unreachable backend (show
// the "set up the local AI" note), offline=false for any other failure (the
// model answered badly, timed out, or the input was rejected).
async function rpostLlm<T>(path: string, body: unknown): Promise<T> {
  let r: Response
  try {
    r = await fetch(`/api/routines${path}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new RoutinesApiError('Could not reach the app backend.', true)
  }
  if (!r.ok) {
    let detail = ''
    try {
      const j = (await r.json()) as { detail?: unknown }
      if (typeof j.detail === 'string') detail = j.detail
    } catch { /* non-JSON error body */ }
    throw new RoutinesApiError(detail || `Request failed (${r.status}).`, r.status === 503)
  }
  return (await r.json()) as T
}

export const routinesApi = {
  catalog: () => rget<RoutineCatalog>('/catalog', { routines: [] }),
  // Throws on failure: an empty digest must mean "nothing due", never "fetch failed".
  deadlineDigest: async (days = 14): Promise<DeadlineDigest> => {
    const r = await fetch(`/api/routines/deadline-digest?days=${days}`)
    if (!r.ok) throw new Error(`deadline digest failed: ${r.status}`)
    return (await r.json()) as DeadlineDigest
  },
  deadlineDigestBrief: (days = 14) =>
    rpostLlm<DeadlineDigestBriefing>('/deadline-digest/brief', { days }),
  essayFeedback: (text: string, promptHint = '') =>
    rpostLlm<EssayFeedback>('/essay-feedback', { text, prompt_hint: promptHint }),
  resumeFeedback: (content: string, title = '') =>
    rpostLlm<ResumeFeedback>('/resume-feedback', { content, title }),
}

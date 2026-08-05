// Scholarship scout client — fires the scout agent with the student's own
// search criteria and polls the run until it finishes. Self-contained, same
// resilient style as the module API clients.

export interface ScoutRun {
  id: string
  status: string // running | completed | failed | ...
  result: string
  error?: string
}

const AGENT = 'scholarship-scout'

export const scoutApi = {
  /** Start a criteria search. Returns the run id, or null if it couldn't start. */
  search: async (criteria: string): Promise<string | null> => {
    try {
      const res = await fetch(`/api/agents/${AGENT}/run`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          trigger_context: {
            search_criteria: criteria,
            source: 'student typed these criteria into the Find Scholarships box',
          },
        }),
      })
      if (!res.ok) return null
      const data = await res.json()
      return (data.id as string) ?? null
    } catch {
      return null
    }
  },

  run: async (id: string): Promise<ScoutRun | null> => {
    try {
      const res = await fetch(`/api/agents/runs/${id}`)
      if (!res.ok) return null
      const data = await res.json()
      const run = data.run ?? data
      return {
        id: run.id,
        status: run.status ?? 'unknown',
        result: run.result ?? '',
        error: run.error,
      }
    } catch {
      return null
    }
  },
}

// Profile API — the stage that drives stage-aware UI. Self-contained client,
// same resilient style as the module API clients.
import type { Stage } from './stageConfig'

export interface Profile {
  stage: Stage | null
  name: string
}

const BASE = '/api/profile'

export const profileApi = {
  get: async (): Promise<Profile> => {
    try {
      const res = await fetch(BASE)
      if (!res.ok) return { stage: null, name: '' }
      return (await res.json()) as Profile
    } catch {
      return { stage: null, name: '' }
    }
  },

  set: async (stage: Stage, name = ''): Promise<boolean> => {
    try {
      const res = await fetch(BASE, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage, name }),
      })
      return res.ok
    } catch {
      return false
    }
  },
}

// Profile API — stage + name + post-undergrad track. Self-contained client,
// same resilient style as the module API clients.
// NOTE: the backend PUT replaces the whole profile file — always send every field.
import type { Stage } from './stageConfig'
import type { Track } from './trackConfig'

export interface Profile {
  stage: Stage | null
  name: string
  track: Track | null
  test_date: string
  reminders: boolean
}

const BASE = '/api/profile'

export const profileApi = {
  /** The saved profile, or null when it could not be read (backend starting,
   *  5xx, bad JSON). null must never be treated as "first run": only a
   *  successful read with stage null means a new user. */
  get: async (): Promise<Profile | null> => {
    try {
      const res = await fetch(BASE)
      if (!res.ok) return null
      return (await res.json()) as Profile
    } catch {
      return null
    }
  },

  set: async (stage: Stage, name = '', track: Track | null = null, testDate = '', reminders = true): Promise<boolean> => {
    try {
      const res = await fetch(BASE, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage, name, track, test_date: testDate, reminders }),
      })
      return res.ok
    } catch {
      return false
    }
  },

  /** Fire today's deadline notification right now (Settings test button). */
  testReminder: async (): Promise<{ sent: boolean; reason?: string } | null> => {
    try {
      const res = await fetch(`${BASE}/reminders/test`, { method: 'POST' })
      if (!res.ok) return null
      return await res.json()
    } catch {
      return null
    }
  },
}

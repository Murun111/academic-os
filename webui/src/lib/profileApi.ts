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

const EMPTY: Profile = { stage: null, name: '', track: null, test_date: '', reminders: true }
const BASE = '/api/profile'

export const profileApi = {
  get: async (): Promise<Profile> => {
    try {
      const res = await fetch(BASE)
      if (!res.ok) return EMPTY
      return (await res.json()) as Profile
    } catch {
      return EMPTY
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

// Self-update API — status polling + install trigger for the Settings
// "update now" panel. Backend contract (backend/routers/update.py +
// backend/services/updater.py — one atomic job, no separate "check only"
// step: POST /install runs check+download+verify+install+relaunch in the
// background, and available_version is only known partway through that job):
//   GET  /api/update/status  -> UpdateStatus
//     state: idle | checking | downloading | verifying | installing | restarting | error
//   POST /api/update/install -> starts the job (202), 409 if one's already
//     running, 400 {error_kind, message} if this build isn't eligible.
//
// The backend route may not exist at all on an older build or a plain
// source checkout — every call here fails soft to null/false so the panel
// can fall back to the legacy "check for updates" link instead of breaking.

export type UpdateErrorKind = 'network_error' | 'verify_error' | 'install_error'

export interface UpdateStatus {
  state: string
  pct?: number | null
  available_version?: string | null
  current_version: string
  eligible: boolean
  eligible_reason?: string | null
  error_kind?: UpdateErrorKind | string | null
  message?: string | null
}

const BASE = '/api/update'

export const updateApi = {
  // Returns null if the endpoint is missing (older build, dev checkout) or
  // unreachable — callers treat null as "fall back to the legacy flow".
  status: async (): Promise<UpdateStatus | null> => {
    try {
      const res = await fetch(`${BASE}/status`)
      if (!res.ok) return null
      return (await res.json()) as UpdateStatus
    } catch {
      return null
    }
  },

  install: async (): Promise<boolean> => {
    try {
      return (await fetch(`${BASE}/install`, { method: 'POST' })).ok
    } catch {
      return false
    }
  },
}

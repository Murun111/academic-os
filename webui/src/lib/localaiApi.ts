// Bundled local AI API — status, model download, server lifecycle.

export interface LocalAiModelInfo {
  label: string
  size_mb: number
  installed: boolean
}

export interface LocalAiStatus {
  binary: boolean
  model: string | null
  models: Record<string, LocalAiModelInfo>
  download: { model: string; pct: number | null; done: boolean; error: string | null } | null
  running: boolean
  port: number
}

const BASE = '/api/localai'
const EMPTY: LocalAiStatus = {
  binary: false, model: null, models: {}, download: null, running: false, port: 11435,
}

export const localaiApi = {
  status: async (): Promise<LocalAiStatus> => {
    try {
      const res = await fetch(`${BASE}/status`)
      return res.ok ? ((await res.json()) as LocalAiStatus) : EMPTY
    } catch {
      return EMPTY
    }
  },

  download: async (model: 'standard' | 'small'): Promise<boolean> => {
    try {
      const res = await fetch(`${BASE}/download`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model }),
      })
      return res.ok
    } catch {
      return false
    }
  },

  start: async (): Promise<boolean> => {
    try {
      return (await fetch(`${BASE}/start`, { method: 'POST' })).ok
    } catch {
      return false
    }
  },

  stop: async (): Promise<boolean> => {
    try {
      return (await fetch(`${BASE}/stop`, { method: 'POST' })).ok
    } catch {
      return false
    }
  },
}

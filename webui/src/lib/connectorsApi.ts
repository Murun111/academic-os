// Connectors API — LMS calendar-feed (ICS) sync. Self-contained client.

export interface IcsSyncResult {
  feeds: number
  created: number
  updated: number
  unchanged: number
  errors: { feed: string; error: string }[]
}

// Feed URLs carry a per-student secret token — the backend never sends the
// full URL to the client, only an id (stable for this list) and the host.
export interface IcsFeed {
  id: number
  host: string
  configured: boolean
}

export interface IcsConfig {
  feeds: IcsFeed[]
  last_sync: string | null
  last_result: IcsSyncResult | null
}

export interface CanvasSyncResult {
  courses: number
  created: number
  updated: number
  unchanged: number
  errors: { scope: string; error: string }[]
}

export interface CanvasConfig {
  base_url: string
  connected: boolean
  token_hint: string
  last_sync: string | null
  last_result: CanvasSyncResult | null
}

const BASE = '/api/connectors/ics'
const CANVAS = '/api/connectors/canvas'
const EMPTY: IcsConfig = { feeds: [], last_sync: null, last_result: null }
const CANVAS_EMPTY: CanvasConfig = {
  base_url: '', connected: false, token_hint: '', last_sync: null, last_result: null,
}

export const connectorsApi = {
  status: async (): Promise<IcsConfig> => {
    try {
      const res = await fetch(BASE)
      return res.ok ? ((await res.json()) as IcsConfig) : EMPTY
    } catch {
      return EMPTY
    }
  },

  addFeed: async (url: string): Promise<boolean> => {
    try {
      const res = await fetch(BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      })
      return res.ok
    } catch {
      return false
    }
  },

  removeFeed: async (id: number): Promise<boolean> => {
    try {
      const res = await fetch(`${BASE}/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      })
      return res.ok
    } catch {
      return false
    }
  },

  sync: async (): Promise<IcsSyncResult | null> => {
    try {
      const res = await fetch(`${BASE}/sync`, { method: 'POST' })
      return res.ok ? ((await res.json()) as IcsSyncResult) : null
    } catch {
      return null
    }
  },

  canvasStatus: async (): Promise<CanvasConfig> => {
    try {
      const res = await fetch(CANVAS)
      return res.ok ? ((await res.json()) as CanvasConfig) : CANVAS_EMPTY
    } catch {
      return CANVAS_EMPTY
    }
  },

  canvasConnect: async (baseUrl: string, token: string): Promise<boolean> => {
    try {
      const res = await fetch(CANVAS, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ base_url: baseUrl, token }),
      })
      return res.ok
    } catch {
      return false
    }
  },

  canvasClear: async (): Promise<boolean> => {
    try {
      const res = await fetch(`${CANVAS}/clear`, { method: 'POST' })
      return res.ok
    } catch {
      return false
    }
  },

  canvasSync: async (): Promise<CanvasSyncResult | null> => {
    try {
      const res = await fetch(`${CANVAS}/sync`, { method: 'POST' })
      return res.ok ? ((await res.json()) as CanvasSyncResult) : null
    } catch {
      return null
    }
  },
}

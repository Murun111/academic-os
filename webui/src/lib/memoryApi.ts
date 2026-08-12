// Memory privacy view — what the app remembers about you, with delete.
// Self-contained client, same resilient style as the module API clients.

export interface MemoryItem {
  item_id: string
  kind: string // fact | decision | todo | preference | entity | event
  subject: string
  body: string
  ts: string
}

export const memoryApi = {
  items: async (): Promise<MemoryItem[]> => {
    try {
      const res = await fetch('/api/memory/items')
      if (!res.ok) return []
      const data = await res.json()
      return (data.items as MemoryItem[]) ?? []
    } catch {
      return []
    }
  },

  forget: async (itemId: string): Promise<boolean> => {
    try {
      const res = await fetch(`/api/memory/items/${itemId}`, { method: 'DELETE' })
      return res.ok
    } catch {
      return false
    }
  },

  forgetAll: async (): Promise<boolean> => {
    try {
      const res = await fetch('/api/memory/forget_all', { method: 'POST' })
      return res.ok
    } catch {
      return false
    }
  },
}

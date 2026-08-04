import type {
  AgentInfo, AgentStats, Approval, Autonomy, ChatMessage, ChatThread,
  EventKind, Health, MemoryEntry, MemoryKind, MemoryStats, OsEvent, Risk,
  Run, RunStatus, TraceStep,
} from './types'
import * as mock from './mock'

// One client, two backends. `real` hits FastAPI on the same origin
// (vite proxies /api and /ws to :7878); `mock` simulates the living system.

export interface OsApi {
  agents(): Promise<AgentInfo[]>
  runs(): Promise<Run[]>
  runAgent(name: string): Promise<void>
  approvals(): Promise<Approval[]>
  decide(id: string, approve: boolean): Promise<void>
  events(onEvent: (e: OsEvent) => void): () => void
  seedEvents(): Promise<OsEvent[]>
  memories(q?: string): Promise<MemoryEntry[]>
  threads(): Promise<ChatThread[]>
  chat(threadId: string | null, text: string, model: string): Promise<ChatMessage[]>
  health(): Promise<Health>
  agentStats(name: string): Promise<AgentStats | null>
  memoryStats(): Promise<MemoryStats>
}

const MODE = (import.meta.env.VITE_API_MODE as string | undefined) ?? 'mock'

/* ------------------------------ mock backend ------------------------------ */

const delay = (ms = 120) => new Promise((r) => setTimeout(r, ms))

const mockApi: OsApi = {
  async agents() { await delay(); return structuredClone(mock.agents) },
  async runs() { await delay(); return structuredClone(mock.runs) },
  async runAgent(name) {
    await delay(200)
    const a = mock.agents.find((x) => x.name === name)
    if (a) { a.state = 'running'; a.currentTask = 'warming up…'; a.runsToday += 1 }
  },
  async approvals() { await delay(); return structuredClone(mock.approvals) },
  async decide(id) {
    await delay(150)
    const i = mock.approvals.findIndex((a) => a.id === id)
    if (i >= 0) mock.approvals.splice(i, 1)
  },
  events(onEvent) {
    // the heartbeat of mock mode: a new event every few seconds,
    // and once in a while a fresh approval escalates for real
    let alive = true
    const tick = () => {
      if (!alive) return
      if (Math.random() < 0.07 && mock.approvals.length < 5) {
        const ap = mock.spawnApproval()
        onEvent({
          id: mock.nextId('ev'), t: new Date().toISOString(), kind: 'approval',
          agent: ap.agent, message: `${ap.tool} escalated (${ap.risk} risk)`,
        })
      } else {
        const src = mock.eventScript[Math.floor(Math.random() * mock.eventScript.length)]
        onEvent({ ...src, id: mock.nextId('ev'), t: new Date().toISOString() })
      }
      setTimeout(tick, 2500 + Math.random() * 4500)
    }
    setTimeout(tick, 1800)
    return () => { alive = false }
  },
  async seedEvents() { return structuredClone(mock.events) },
  async memories(q) {
    await delay()
    const all = structuredClone(mock.memories)
    if (!q) return all
    const needle = q.toLowerCase()
    return all.filter((m) => (m.text + m.source + m.kind).toLowerCase().includes(needle))
  },
  async threads() { await delay(); return structuredClone(mock.threads) },
  async chat(_threadId, text, _model) {
    await delay(900 + Math.random() * 900)
    const reply: ChatMessage = {
      role: 'assistant', t: new Date().toISOString(), tokens: 200 + Math.floor(Math.random() * 400),
      elapsedMs: 3000 + Math.floor(Math.random() * 4000),
      content: `(mock) Understood. In real mode this call POSTs /api/llms/chat, recalls memory for “${text.slice(0, 48)}…”, injects it as a system message for this turn, and consolidates the thread afterwards.`,
    }
    return [
      { role: 'memory', content: '2 entries recalled and injected for this turn', t: new Date().toISOString() },
      reply,
    ]
  },
  async health() { await delay(); return { ...mock.health } },
  async agentStats(name) { await delay(); return structuredClone(mock.agentStats[name] ?? null) },
  async memoryStats() { await delay(); return structuredClone(mock.memoryStats) },
}

/* ------------------------------ real backend ------------------------------ */

// The FastAPI backend (backend/app.py) speaks a different, richer shape than the
// mock contract. This layer maps real routes → the typed contract the UI expects,
// and degrades gracefully: unconfigured services (browser) or endpoints the
// backend doesn't expose (memory/agent stats) fall back to empty/synthesized
// values instead of 500ing a panel. Everything the components consume stays
// contract-true.

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${path} → ${r.status}`)
  return r.json()
}

// resilient GET/POST: return a fallback on any error or non-2xx so a single
// offline service can't take down the whole view.
async function tryGet<T>(path: string, fallback: T): Promise<T> {
  try {
    const r = await fetch(`/api${path}`)
    if (!r.ok) return fallback
    return (await r.json()) as T
  } catch { return fallback }
}
async function postSafe(path: string, body: unknown): Promise<any> {
  try {
    const r = await fetch(`/api${path}`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    return await r.json()
  } catch (e) { return { error: String(e) } }
}

/* --- small helpers --- */

const basename = (p: string) => (p || '').split('/').pop() || p
let evSeq = 0
const evId = () => `ev_${Date.now()}_${evSeq++}`

// runs are appended twice (RUNNING then a terminal record); keep the last per id.
function dedupeRuns(runs: any[]): any[] {
  const m = new Map<string, any>()
  for (const r of runs) if (r?.id) m.set(r.id, r)
  return [...m.values()]
}

const FAILED_STATES = ['failed', 'timeout', 'cancelled', 'interrupted']

function mapRunStatus(s: string, escalations: number): RunStatus {
  if (s === 'success') return 'completed'
  if (FAILED_STATES.includes(s)) return s === 'interrupted' ? 'interrupted' : 'failed'
  if (s === 'running' || s === 'pending') return escalations > 0 ? 'waiting_approval' : 'running'
  return 'running'
}

function runGoal(r: any): string {
  const t = String(r.trigger || '')
  if (t === 'manual') return 'Manual run'
  if (t === 'cron' || t === 'scheduled') return 'Scheduled run'
  if (t.startsWith('vault_event')) return 'Vault-triggered run'
  if (r.result) return String(r.result).split('\n')[0].slice(0, 80)
  return `${r.agent} run`
}

function runSteps(r: any): TraceStep[] {
  const steps: TraceStep[] = (r.tool_calls || []).map((tc: any): TraceStep => ({
    t: r.started_at,
    kind: tc.gate ? 'gate' : 'tool',
    label: tc.tool || 'tool',
    detail: tc.result_preview,
    ok: !tc.gate,
  }))
  if (r.critic) {
    steps.push({
      t: r.finished_at || r.started_at, kind: 'critic', label: 'critic',
      detail: r.critic.reason, ok: r.critic.verdict !== 'fail',
    })
  }
  if (r.result || r.error) {
    steps.push({
      t: r.finished_at || r.started_at, kind: 'result',
      label: r.error ? 'error' : 'result',
      detail: String(r.error || r.result || '').slice(0, 200), ok: !r.error,
    })
  }
  return steps
}

function riskOf(tool: string): Risk {
  const t = tool.toLowerCase()
  if (/delete|remove|\brm\b|send|email|pay|money|transfer|push|deploy|write/.test(t)) return 'high'
  if (/schedule|update|edit|create|move|set_/.test(t)) return 'medium'
  return 'low'
}

function mapMemKind(k: string): MemoryKind {
  if (k === 'preference') return 'preference'
  if (k === 'entity') return 'entity'
  if (k === 'fact') return 'fact'
  return 'trajectory' // decision | todo | event → trajectory bucket
}

function eventTime(ts: any): string {
  if (typeof ts === 'number') return new Date(ts < 1e12 ? ts * 1000 : ts).toISOString()
  if (typeof ts === 'string' && ts) {
    const d = new Date(ts)
    return isNaN(+d) ? new Date().toISOString() : d.toISOString()
  }
  return new Date().toISOString()
}

// backend "HH:MM" (activity feed) → today's ISO so timeAgo() reads it.
function timeToIso(hhmm: string): string {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm || '')
  if (!m) return new Date().toISOString()
  const d = new Date()
  d.setHours(Number(m[1]), Number(m[2]), 0, 0)
  return d.toISOString()
}

function mapEvent(raw: any): OsEvent | null {
  const type = raw?.type
  if (!type || type === 'hello' || type === 'ping') return null
  const base = { id: evId(), t: eventTime(raw.ts) }
  switch (type) {
    case 'vault_event':
      return { ...base, kind: 'vault', message: `${raw.kind || 'changed'} · ${basename(raw.path || '')}` }
    case 'agent.run':
      return { ...base, kind: 'agent', agent: raw.agent, message: `${raw.agent || 'agent'} ${raw.phase || ''}${raw.tool ? ` · ${raw.tool}` : ''}`.trim() }
    case 'approval':
      // keep the word "escalated" — store.ts keys the approval-refresh + toast on it
      return { ...base, kind: 'approval', agent: raw.agent, message: `${raw.tool || 'action'} escalated${raw.count > 1 ? ` (${raw.count})` : ''}` }
    case 'cos':
      return { ...base, kind: 'system', message: `chief of staff · ${raw.phase || 'update'}` }
    case 'memory':
      return { ...base, kind: 'memory', message: raw.message || 'memory updated' }
    default:
      return { ...base, kind: 'system', message: raw.message || String(type) }
  }
}

const realApi: OsApi = {
  async agents() {
    const [aRes, rRes] = await Promise.all([
      tryGet<any>('/agents', { agents: [] }),
      tryGet<any>('/agents/runs?limit=400', { runs: [] }),
    ])
    const runs = dedupeRuns(rRes.runs || [])
    const todayStr = new Date().toDateString()
    return (aRes.agents || []).map((s: any): AgentInfo => {
      const mine = runs
        .filter((r) => r.agent === s.name)
        .sort((a, b) => (a.started_at < b.started_at ? -1 : 1))
      const latest = mine[mine.length - 1]
      const running = mine.some((r) => r.status === 'running' || r.status === 'pending')
      const failed = latest && FAILED_STATES.includes(latest.status)
      const runsToday = mine.filter((r) => {
        try { return new Date(r.started_at).toDateString() === todayStr } catch { return false }
      }).length
      // real per-agent signals from run history: tools actually invoked, and
      // whether any run escalated for approval (autonomy is never in the spec).
      const tools = [...new Set(
        mine.flatMap((r) => (r.tool_calls || []).map((tc: any) => tc.tool as string).filter(Boolean)),
      )]
      const gated = mine.some((r) => (r.escalations || []).length > 0)
      const scheduled = !!s.schedule || (!!s.trigger && s.trigger !== 'manual')
      const autonomy: Autonomy = gated ? 'gated' : scheduled ? 'auto' : 'manual'
      return {
        name: s.name,
        description: s.description || '',
        state: running ? 'running' : failed ? 'failed' : 'idle',
        autonomy,
        currentTask: running ? 'working…' : undefined,
        lastRun: latest?.started_at,
        runsToday,
        tools,
      }
    })
  },

  async runs() {
    const res = await tryGet<any>('/agents/runs?limit=200', { runs: [] })
    return dedupeRuns(res.runs || [])
      .map((r: any): Run => ({
        id: r.id,
        agent: r.agent,
        goal: runGoal(r),
        status: mapRunStatus(r.status, (r.escalations || []).length),
        startedAt: r.started_at,
        elapsedMs: r.duration_seconds ? Math.round(r.duration_seconds * 1000) : undefined,
        steps: runSteps(r),
      }))
      .reverse() // newest first
  },

  async runAgent(name) { await post(`/agents/${encodeURIComponent(name)}/run`, {}) },

  async approvals() {
    const res = await tryGet<any>('/approvals', { pending: [] })
    return (res.pending || []).map((p: any): Approval => ({
      id: p.id,
      agent: p.agent || '',
      tool: p.tool || '',
      args: Object.fromEntries(
        Object.entries(p.args || {}).map(([k, v]) => [k, typeof v === 'string' ? v : JSON.stringify(v)]),
      ),
      reason: p.reason || '',
      requestedAt: p.ts || new Date().toISOString(),
      risk: riskOf(p.tool || ''),
    }))
  },

  async decide(id, approve) {
    await postSafe('/approvals/decide', { item_id: id, decision: approve ? 'approved' : 'dismissed' })
  },

  events(onEvent) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    let ws: WebSocket | null = null
    let closed = false
    const connect = () => {
      ws = new WebSocket(`${proto}://${location.host}/ws/events`)
      ws.onmessage = (m) => {
        try { const ev = mapEvent(JSON.parse(m.data)); if (ev) onEvent(ev) } catch { /* skip malformed frame */ }
      }
      ws.onclose = () => { if (!closed) setTimeout(connect, 2000) }
    }
    connect()
    return () => { closed = true; ws?.close() }
  },

  async seedEvents() {
    const res = await tryGet<any>('/activity/recent?limit=30', { items: [] })
    const kindMap: Record<string, EventKind> = { run: 'agent', code: 'agent', cos: 'system', brief: 'system' }
    return (res.items || []).map((it: any): OsEvent => ({
      id: evId(),
      t: timeToIso(it.time || ''),
      kind: kindMap[it.kind] || 'system',
      agent: it.kind === 'run' ? String(it.label || '').toLowerCase() : undefined,
      message: `${it.label || ''}${it.sub ? ` · ${it.sub}` : ''}`.trim(),
    }))
  },

  async memories(q) {
    const res = await tryGet<any>(`/memory/search?q=${encodeURIComponent(q || '')}&k=100`, { results: [] })
    return (res.results || []).map((m: any): MemoryEntry => ({
      id: m.item_id || m.vault_path || evId(),
      kind: mapMemKind(m.kind),
      text: m.body || m.subject || '',
      source: basename(m.vault_path || '') || 'vault',
      t: m.ts || new Date().toISOString(),
      strength: 0.6,
    }))
  },

  async threads() {
    const res = await tryGet<any>('/llms/history', { threads: [] })
    const summaries = (res.threads || []).slice(0, 20)
    const full = await Promise.all(
      summaries.map((s: any) => tryGet<any>(`/llms/history/${encodeURIComponent(s.id)}`, null)),
    )
    return summaries.map((s: any, i: number): ChatThread => {
      const f = full[i]
      const messages: ChatMessage[] = (f?.messages || []).map((m: any): ChatMessage => ({
        role: m.role === 'assistant' ? 'assistant' : m.role === 'user' ? 'user' : 'memory',
        content: m.content || '',
        t: m.ts || '',
        tokens: m.tokens,
        elapsedMs: m.elapsed_ms,
      }))
      return {
        id: s.id,
        title: s.title || '(untitled)',
        model: s.model || '',
        updated: f?.updated_at || s.created_at || '',
        messages,
      }
    })
  },

  async chat(threadId, text, model) {
    const res = await postSafe('/llms/chat', {
      thread_id: threadId, messages: [{ role: 'user', content: text }], model, backend: 'ollama',
    })
    if (res?.error) {
      return [{ role: 'assistant', content: `error: ${res.error}`, t: new Date().toISOString() }]
    }
    return [{
      role: 'assistant',
      content: res.content || '',
      t: new Date().toISOString(),
      tokens: res.tokens,
      elapsedMs: res.elapsed_ms,
    }]
  },

  async health() {
    const [ready, browser] = await Promise.all([
      tryGet<any>('/health/ready', { ollama: false }),
      tryGet<any>('/browser/health', null),
    ])
    return {
      backend: 'ok',
      ollama: ready?.ollama ? 'ok' : 'degraded',
      caldav: 'ok',
      browser: browser ? 'ok' : 'offline',
    } as Health
  },

  async agentStats(name) {
    const res = await tryGet<any>(`/agents/runs?agent=${encodeURIComponent(name)}&limit=500`, { runs: [] })
    const runs = dedupeRuns(res.runs || [])
    const today = new Date(); today.setHours(0, 0, 0, 0)
    const runsByDay = new Array(7).fill(0)
    let completed = 0, failed = 0
    for (const r of runs) {
      if (r.status === 'success') completed++
      else if (FAILED_STATES.includes(r.status)) failed++
      try {
        const d = new Date(r.started_at)
        const diff = Math.floor((+today - +new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000)
        if (diff >= 0 && diff < 7) runsByDay[6 - diff]++
      } catch { /* skip unparseable stamp */ }
    }
    return { runsByDay, completed, failed }
  },

  // /api/memory/stats: real by-kind distribution + 30-day cumulative growth from
  // the memory index. Backend's 6 raw kinds collapse into the UI's 4 buckets.
  async memoryStats() {
    const s = await tryGet<any>('/memory/stats', { by_kind: {}, growth: [] })
    const byKind: Record<MemoryKind, number> = { fact: 0, preference: 0, trajectory: 0, entity: 0 }
    for (const [k, n] of Object.entries(s.by_kind || {})) byKind[mapMemKind(k)] += n as number
    return { growth: s.growth || [], byKind } as MemoryStats
  },
}

export const api: OsApi = MODE === 'real' ? realApi : mockApi
export const apiMode = MODE

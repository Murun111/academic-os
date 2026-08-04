// Contract types mirroring the FastAPI backend (backend/app.py, /api/*, /ws/events).

export type AgentState = 'running' | 'idle' | 'failed'
export type Autonomy = 'auto' | 'gated' | 'manual'

export interface AgentInfo {
  name: string
  description: string
  state: AgentState
  autonomy: Autonomy
  currentTask?: string
  lastRun?: string // ISO
  runsToday: number
  tools: string[]
}

export type RunStatus = 'running' | 'completed' | 'failed' | 'waiting_approval' | 'interrupted'

export interface TraceStep {
  t: string
  kind: 'tool' | 'llm' | 'critic' | 'gate' | 'result'
  label: string
  detail?: string
  ok: boolean
  durMs?: number
}

export interface Run {
  id: string
  agent: string
  goal: string
  status: RunStatus
  startedAt: string
  elapsedMs?: number
  tokens?: number
  steps: TraceStep[]
}

export type Risk = 'low' | 'medium' | 'high'

export interface Approval {
  id: string
  agent: string
  tool: string
  args: Record<string, string>
  reason: string
  requestedAt: string
  risk: Risk
}

export type EventKind = 'vault' | 'agent' | 'trigger' | 'memory' | 'kb' | 'approval' | 'system'

export interface OsEvent {
  id: string
  t: string
  kind: EventKind
  message: string
  agent?: string
}

export type MemoryKind = 'fact' | 'preference' | 'trajectory' | 'entity'

export interface MemoryEntry {
  id: string
  kind: MemoryKind
  text: string
  source: string
  t: string
  strength: number // 0..1
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'memory'
  content: string
  t: string
  tokens?: number
  elapsedMs?: number
}

export interface ChatThread {
  id: string
  title: string
  model: string
  updated: string
  messages: ChatMessage[]
}

export type ServiceState = 'ok' | 'degraded' | 'offline'

export interface Health {
  backend: ServiceState
  ollama: ServiceState
  caldav: ServiceState
  browser: ServiceState
}

export interface AgentStats {
  runsByDay: number[] // last 7 days, oldest first
  completed: number
  failed: number
}

export interface MemoryStats {
  growth: number[] // cumulative entry count, last 30 days, oldest first
  byKind: Record<MemoryKind, number>
}

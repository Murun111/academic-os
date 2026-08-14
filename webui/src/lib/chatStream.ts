import type { ChatMessage } from './types'

// Streaming client for the Chat tab. Kept out of lib/api.ts on purpose: that
// file is shared with Agents.tsx, and this module's parsing needs to stay
// free to evolve (or be deleted) without touching another feature's surface.
//
// Talks to POST /api/llms/chat/stream (backend/app.py:llms_chat_stream), an
// SSE endpoint. The live backend emits {"token": "<piece>"} per chunk and
// {"done": true, "thread_id", "content", "tokens"} at the end — this parser
// also accepts the spec shape ({"delta"...}, {"done": true, "message": {...}})
// so either wire format renders correctly.

const AI_MISSING = "The local AI isn't set up yet — download it in Settings → Local AI."
const CHAT_FAILED = 'Something went wrong talking to the AI — try again, or restart the app.'

function friendlyStreamError(raw: string): string {
  const low = (raw || '').toLowerCase()
  if (low.includes('no local ai') || low.includes('not installed')) return AI_MISSING
  return CHAT_FAILED
}

function assistantSay(content: string): ChatMessage {
  return { role: 'assistant', content, t: new Date().toISOString() }
}

export type StreamResult =
  // stream produced a final message (success or a friendly error message)
  | { kind: 'streamed'; message: ChatMessage }
  // caller aborted — partial text already reached the UI via onDelta;
  // nothing further to append, no error to show
  | { kind: 'aborted' }
  // stream endpoint doesn't exist on this backend — caller should retry
  // against the non-streaming endpoint
  | { kind: 'fallback' }

/**
 * POSTs to /api/llms/chat/stream and reports each text chunk via onDelta as
 * it arrives. Resolves once the stream ends (done event, error, EOF, or
 * abort) rather than rejecting, so callers don't need a catch for the normal
 * cancel path.
 */
export async function streamChat(
  threadId: string | null,
  text: string,
  model: string,
  onDelta: (piece: string) => void,
  signal: AbortSignal,
): Promise<StreamResult> {
  let r: Response
  try {
    r = await fetch('/api/llms/chat/stream', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        thread_id: threadId,
        messages: [{ role: 'user', content: text }],
        model,
        backend: 'ollama',
      }),
      signal,
    })
  } catch {
    if (signal.aborted) return { kind: 'aborted' }
    return { kind: 'streamed', message: assistantSay(CHAT_FAILED) }
  }

  if (r.status === 404) return { kind: 'fallback' }
  if (!r.ok || !r.body) {
    const body = await r.text().catch(() => '')
    return { kind: 'streamed', message: assistantSay(friendlyStreamError(body)) }
  }

  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  const started = Date.now()
  let buf = ''
  let full = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const frames = buf.split('\n\n')
      buf = frames.pop() ?? '' // last chunk may be a partial frame — keep it for next read
      for (const frame of frames) {
        for (const line of frame.split('\n')) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data:')) continue
          const jsonStr = trimmed.slice(5).trim()
          if (!jsonStr) continue
          let evt: Record<string, unknown>
          try {
            evt = JSON.parse(jsonStr)
          } catch {
            continue // skip a malformed frame rather than killing the stream
          }

          if (evt.error) {
            return { kind: 'streamed', message: assistantSay(friendlyStreamError(String(evt.error))) }
          }

          const piece = (evt.delta ?? evt.token) as string | undefined
          if (typeof piece === 'string' && piece) {
            full += piece
            onDelta(piece)
          }

          if (evt.done) {
            const m = evt.message as Partial<ChatMessage> | undefined
            const content = (m?.content ?? (evt.content as string | undefined) ?? full) as string
            const tokens = (m?.tokens ?? (evt.tokens as number | undefined)) as number | undefined
            const elapsedMs = m?.elapsedMs ?? Date.now() - started
            if (!content.trim()) return { kind: 'streamed', message: assistantSay(CHAT_FAILED) }
            return {
              kind: 'streamed',
              message: { role: 'assistant', content, t: new Date().toISOString(), tokens, elapsedMs },
            }
          }
        }
      }
    }
  } catch {
    if (signal.aborted) return { kind: 'aborted' }
    return { kind: 'streamed', message: assistantSay(CHAT_FAILED) }
  }

  // stream closed without a done event — whatever text arrived is all there is
  if (full.trim()) {
    return {
      kind: 'streamed',
      message: { role: 'assistant', content: full, t: new Date().toISOString(), elapsedMs: Date.now() - started },
    }
  }
  return { kind: 'streamed', message: assistantSay(CHAT_FAILED) }
}

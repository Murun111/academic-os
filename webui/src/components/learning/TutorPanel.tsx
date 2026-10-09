import { useEffect, useRef, useState } from 'react'
import { Loader2, Send } from 'lucide-react'
import { learning, LearningApiError, type TutorMessage } from '../../lib/learningApi'
import { Btn, EmptyState, Panel, PanelHead } from '../ui'

export function TutorPanel() {
  const [topic, setTopic] = useState('')
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<TutorMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end' })
  }, [messages, loading])

  const canSend = !loading && topic.trim() !== '' && input.trim() !== ''

  const send = async () => {
    if (!canSend) return
    const sent = input
    const next: TutorMessage[] = [...messages, { role: 'user', content: sent.trim() }]
    setMessages(next)
    setInput('')
    setError(null)
    setLoading(true)
    try {
      const res = await learning.tutor({ topic: topic.trim(), messages: next })
      setMessages([...next, { role: 'assistant', content: res.reply }])
    } catch (e) {
      // Put the question back and drop the orphaned turn so a retry sends one user message.
      setMessages(messages)
      setInput((cur) => (cur.trim() === '' ? sent : cur))
      if (e instanceof LearningApiError && e.status === 503) {
        setError('The local AI tutor is not available right now. Start your local model and try again.')
      } else if (e instanceof LearningApiError && e.status === 502) {
        setError('The tutor answered in a format the app could not read. Try sending it again.')
      } else {
        setError('The tutor could not reply. Check your connection and try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <Panel>
      <PanelHead label="tutor" />
      <div className="px-5 pb-4">
        <label className="label-mono mb-1 block" htmlFor="tutor-topic">topic</label>
        <input
          id="tutor-topic"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="What are you studying? e.g. Krebs cycle"
          className="mb-4 w-full rounded-md border border-line bg-transparent px-2 py-1.5 text-[13px] text-hi placeholder:text-low focus:outline-none"
        />

        <div
          className="mb-3 flex max-h-[420px] min-h-[160px] flex-col gap-2 overflow-y-auto"
          role="log"
          aria-live="polite"
          aria-label="Tutor conversation"
        >
          {messages.length === 0 && !loading && !error && (
            <EmptyState title="Ask your tutor anything" hint="Set a topic, then ask a question." />
          )}
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[85%] whitespace-pre-wrap rounded-[10px] px-3 py-2 text-[13px] ${
                  m.role === 'user' ? 'bg-ink/8 text-hi' : 'border border-line text-mid'
                }`}
              >
                {m.content}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex items-center gap-2 px-1 text-[13px] text-low" role="status">
              <Loader2 size={13} className="animate-spin" aria-hidden="true" /> Tutor is thinking…
            </div>
          )}
          <div ref={endRef} />
        </div>

        {error && (
          <p role="alert" className="mb-3 text-[13px] text-fail">{error}</p>
        )}

        <div className="flex items-center gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              // Enter that confirms an IME candidate (keyCode 229) must not send.
              if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing || e.keyCode === 229) return
              void send()
            }}
            placeholder="Ask a question…"
            aria-label="Message to tutor"
            className="flex-1 rounded-md border border-line bg-transparent px-2 py-1.5 text-[13px] text-hi placeholder:text-low focus:outline-none"
          />
          <Btn kind="primary" onClick={() => void send()} disabled={!canSend}>
            <span className="flex items-center gap-1.5"><Send size={13} /> Send</span>
          </Btn>
        </div>
      </div>
    </Panel>
  )
}

import { motion, AnimatePresence } from 'framer-motion'
import { useOs } from '../lib/store'
import { Btn, Copyable, EmptyState, Mono, Pill, timeAgo } from '../components/ui'

export function Approvals() {
  const { approvals, decide } = useOs()

  return (
    <div className="mx-auto max-w-[820px]">
      <div className="mb-6">
        <p className="label-mono mb-1">nothing happens without your ok</p>
        <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Approvals</h1>
      </div>

      {approvals.length === 0 ? (
        <div className="panel">
          <EmptyState title="Nothing is waiting on you." hint="Gated tool calls will appear here the moment an agent escalates." />
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <AnimatePresence initial={false}>
            {approvals.map((a) => (
              <motion.div
                key={a.id}
                layout
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.18 } }}
                transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
                className="panel px-6 py-5"
              >
                <div className="mb-3 flex items-center gap-3">
                  <Mono className="text-[13px] text-hi">{a.tool}</Mono>
                  <Pill tone={a.risk === 'high' ? 'high' : a.risk === 'medium' ? 'medium' : undefined}>
                    {a.risk} risk
                  </Pill>
                  <span className="ml-auto font-mono text-[11px] text-low">
                    {a.agent} · {timeAgo(a.requestedAt)} ago
                  </span>
                </div>

                <p className="mb-3 max-w-[64ch] text-[13px] leading-relaxed text-mid">{a.reason}</p>

                {/* args as a quiet mono table, not a JSON dump */}
                <div className="mb-4 rounded-[10px] border border-hairline">
                  {Object.entries(a.args).map(([k, v], i) => (
                    <div
                      key={k}
                      className={`flex gap-4 px-3.5 py-2 ${i > 0 ? 'border-t border-hairline' : ''}`}
                    >
                      <Mono className="w-[110px] shrink-0 text-low">{k}</Mono>
                      <Copyable text={v} className="min-w-0 flex-1">
                        <Mono className="min-w-0 break-words text-mid">{v}</Mono>
                      </Copyable>
                    </div>
                  ))}
                </div>

                <div className="flex gap-2">
                  <Btn kind="primary" onClick={() => void decide(a.id, true)}>Approve</Btn>
                  <Btn kind="danger" onClick={() => void decide(a.id, false)}>Deny</Btn>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}

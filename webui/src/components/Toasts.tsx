import { AnimatePresence, motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { X } from 'lucide-react'
import { useOs } from '../lib/store'
import { StatusDot } from './ui'

export function Toasts() {
  const toasts = useOs((s) => s.toasts)
  const dismiss = useOs((s) => s.dismissToast)
  const navigate = useNavigate()

  return (
    <div className="fixed right-5 bottom-5 z-40 flex flex-col gap-2">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            layout
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 16, transition: { duration: 0.16 } }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            className="glass-strong flex items-center gap-3 rounded-[14px] py-2.5 pr-2.5 pl-4"
          >
            <StatusDot state="pending" live />
            <button
              onClick={() => {
                dismiss(t.id)
                if (t.to) navigate(t.to)
              }}
              className="font-mono text-[12px] text-mid transition-colors hover:text-hi"
            >
              {t.text}
            </button>
            <button
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss"
              className="grid size-6 place-items-center rounded-md text-low transition-colors hover:bg-black/5 hover:text-mid"
            >
              <X size={12} />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}

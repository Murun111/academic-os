import { useCallback, useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { LucideIcon } from 'lucide-react'

// Right-click accelerator. Every action here must also exist as a visible
// affordance elsewhere — this is a shortcut, never the only path.

export interface MenuItem {
  label: string
  icon?: LucideIcon
  danger?: boolean
  onSelect: () => void
}

interface MenuState {
  x: number
  y: number
  items: MenuItem[]
}

export function useContextMenu() {
  const [menu, setMenu] = useState<MenuState | null>(null)

  const openMenu = useCallback((e: React.MouseEvent, items: MenuItem[]) => {
    e.preventDefault()
    e.stopPropagation()
    setMenu({
      x: Math.min(e.clientX, window.innerWidth - 200),
      y: Math.min(e.clientY, window.innerHeight - items.length * 34 - 20),
      items,
    })
  }, [])

  const closeMenu = useCallback(() => setMenu(null), [])

  useEffect(() => {
    if (!menu) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeMenu() }
    window.addEventListener('click', closeMenu)
    window.addEventListener('contextmenu', closeMenu)
    window.addEventListener('keydown', onKey)
    window.addEventListener('scroll', closeMenu, true)
    return () => {
      window.removeEventListener('click', closeMenu)
      window.removeEventListener('contextmenu', closeMenu)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', closeMenu, true)
    }
  }, [menu, closeMenu])

  return { menu, openMenu, closeMenu }
}

export function ContextMenu({ menu, onClose }: { menu: MenuState | null; onClose: () => void }) {
  return (
    <AnimatePresence>
      {menu && (
        <motion.div
          className="glass-strong fixed z-50 min-w-[180px] rounded-[12px] p-1"
          style={{ left: menu.x, top: menu.y }}
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.1 } }}
          transition={{ duration: 0.14, ease: [0.22, 1, 0.36, 1] }}
          role="menu"
        >
          {menu.items.map((it) => (
            <button
              key={it.label}
              role="menuitem"
              onClick={() => { it.onSelect(); onClose() }}
              className={`flex w-full items-center gap-2.5 rounded-[8px] px-2.5 py-[7px] text-left text-[13px] transition-colors duration-100 ${
                it.danger ? 'text-fail hover:bg-fail/10' : 'text-mid hover:bg-black/5 hover:text-hi'
              }`}
            >
              {it.icon && <it.icon size={13} strokeWidth={1.75} />}
              {it.label}
            </button>
          ))}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

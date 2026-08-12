import { useEffect } from 'react'
import { HashRouter, Route, Routes, useLocation } from 'react-router-dom'
import { AnimatePresence, MotionConfig, motion } from 'framer-motion'
import { Backdrop } from './components/Backdrop'
import { Sidebar } from './components/Sidebar'
import { CommandPalette } from './components/CommandPalette'
import { StageSetup } from './components/StageSetup'
import { Tour } from './components/Tour'
import { Toasts } from './components/Toasts'
import { useOs } from './lib/store'
import { Dashboard } from './pages/Dashboard'
import { Chat } from './pages/Chat'
import { Applications } from './pages/Applications'
import { Courses } from './pages/Courses'
import { Study } from './pages/Study'
import { Documents } from './pages/Documents'
import { Routines } from './pages/Routines'
import { Agents } from './pages/Agents'
import { Approvals } from './pages/Approvals'
import { Settings } from './pages/Settings'
import { Calendar } from './pages/Calendar'

const TITLES: Record<string, string> = {
  '/': 'Dashboard', '/applications': 'Applications', '/courses': 'Courses', '/study': 'Study',
  '/calendar': 'Calendar', '/documents': 'Documents', '/routines': 'Routines', '/chat': 'Chat',
  '/agents': 'Assistants', '/approvals': 'Approvals', '/settings': 'Settings',
}

import { NO_MOTION } from './lib/motion'

function Shell() {
  const boot = useOs((s) => s.boot)
  const location = useLocation()
  useEffect(() => boot(), [boot])
  useEffect(() => {
    document.title = TITLES[location.pathname] ? `${TITLES[location.pathname]} · Academic OS` : 'Academic OS'
  }, [location.pathname])

  const routes = (
    <Routes location={location}>
      <Route path="/" element={<Dashboard />} />
      <Route path="/applications" element={<Applications />} />
      <Route path="/courses" element={<Courses />} />
      <Route path="/study" element={<Study />} />
      <Route path="/calendar" element={<Calendar />} />
      <Route path="/documents" element={<Documents />} />
      <Route path="/routines" element={<Routines />} />
      <Route path="/chat" element={<Chat />} />
      <Route path="/agents" element={<Agents />} />
      <Route path="/approvals" element={<Approvals />} />
      <Route path="/settings" element={<Settings />} />
    </Routes>
  )

  if (NO_MOTION) {
    return (
      <div className="h-full">
        <Backdrop />
        <Sidebar />
        <CommandPalette />
        <Tour />
        <Toasts />
        <main className="fixed top-0 right-0 bottom-0 left-[92px] overflow-hidden lg:left-[254px]">
          <div className="h-full overflow-y-auto px-7 py-6">{routes}</div>
        </main>
      </div>
    )
  }

  return (
    <div className="h-full">
      <Backdrop />
      <Sidebar />
      <CommandPalette />
      <StageSetup />
      <Tour />
      <Toasts />
      <main className="fixed top-0 right-0 bottom-0 left-[92px] overflow-hidden lg:left-[254px]">
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            className="h-full overflow-y-auto px-7 py-6"
            initial={{ opacity: 0, y: 8, filter: 'blur(4px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            exit={{ opacity: 0, y: -4, filter: 'blur(3px)' }}
            transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
          >
            {routes}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <HashRouter>
        <Shell />
      </HashRouter>
    </MotionConfig>
  )
}

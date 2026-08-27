// ACT Blitz — a private ACT-prep game, visible only when the profile name is
// the secret unlock string below. The game itself is a fully self-contained,
// offline index.html served as a static asset (webui/public/act-blitz/), shown
// in an isolated iframe so its styles/scripts never touch the app. The unlock
// string is an arbitrary token (NOT anyone's real name), so hardcoding it in
// the public repo leaks nothing — set a profile's name to it and the game
// appears; everyone else never sees it. Survives updates (profile lives in the
// data root, untouched by app updates).
import { Navigate } from 'react-router-dom'
import { useOs } from '../lib/store'

export const ACT_GAME_UNLOCK_NAME = 'PinkGlitterFart$parkles'

export function ActPrep() {
  const userName = useOs((s) => s.userName)
  // Hidden unless the secret name is set — a stray navigation to /act-prep on
  // any other copy just bounces to the dashboard.
  if (userName !== ACT_GAME_UNLOCK_NAME) return <Navigate to="/" replace />

  return (
    <div className="mx-auto flex h-full max-w-[1100px] flex-col">
      <div className="mb-4">
        <p className="label-mono mb-1">just for you</p>
        <h1 className="text-[24px] font-semibold tracking-[-0.01em]">ACT Blitz</h1>
      </div>
      <iframe
        title="ACT Blitz — Beat the Clock"
        src="/act-blitz/index.html"
        className="min-h-0 w-full flex-1 rounded-[14px] border border-line bg-raise"
      />
    </div>
  )
}

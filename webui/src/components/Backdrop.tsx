// Layer 0: the monochrome paper world the glass picks up.
// Three soft shade blobs drifting on 60-90s loops + fine grain.

const NOISE =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)' opacity='0.35'/%3E%3C/svg%3E\")"

const blob = (size: string, x: string, y: string, alpha: number, anim: string, dur: string) => ({
  position: 'absolute' as const,
  width: size,
  height: size,
  left: x,
  top: y,
  borderRadius: '50%',
  background: `radial-gradient(circle, color-mix(in oklch, var(--backdrop-blob) ${alpha}%, transparent) 0%, transparent 65%)`,
  animation: `${anim} ${dur} ease-in-out infinite`,
  willChange: 'transform',
})

export function Backdrop() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 overflow-hidden">
      <div style={blob('55vw', '-12vw', '-18vh', 8, 'drift-a', '75s')} />
      <div style={blob('48vw', '55vw', '30vh', 6, 'drift-b', '90s')} />
      <div style={blob('40vw', '20vw', '65vh', 5, 'drift-c', '62s')} />
      {/* faint vertical falloff so the top of the screen breathes */}
      <div
        className="absolute inset-0"
        style={{ background: 'linear-gradient(180deg, var(--backdrop-falloff) 0%, transparent 30%)' }}
      />
      <div className="absolute inset-0 mix-blend-overlay opacity-[0.05]" style={{ backgroundImage: NOISE }} />
    </div>
  )
}

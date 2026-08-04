# DESIGN.md

## Theme

Dark only. Scene: the owner glancing at agent activity on a MacBook at night in a dim room; surfaces must not glare, live signals must be findable at a glance.

## Color (OKLCH, monochrome frost)

Neutrals are tinted cool (hue ~250, chroma 0.004-0.008). Never pure #000/#fff.

- `--bg-deep`: oklch(0.13 0.006 250)  — page backdrop base
- `--bg-raise`: oklch(0.17 0.007 250) — solid content surfaces
- `--glass`: white at 4-7% alpha + backdrop-blur(20-32px) — structural chrome only (sidebar, cmd-k, floating panels, toasts)
- `--line`: white at 8% alpha (borders, 1px only; hairlines at 6%)
- `--text-hi`: oklch(0.96 0.004 250)
- `--text-mid`: oklch(0.72 0.006 250)
- `--text-low`: oklch(0.52 0.008 250)

Status (the only chroma in the system, used at ≤10% of any screen):

- running / ok: oklch(0.78 0.14 160) (green)
- pending / gated: oklch(0.80 0.13 80) (amber)
- failed / blocked: oklch(0.68 0.17 25) (red)
- info / link-ish: text-hi with underline, not blue

Color strategy: Restrained. The backdrop carries slow-drifting monochrome light blobs + fine grain; glass picks these up.

## Typography

- UI sans: Geist (variable), fallback Inter/system. Body 14px/1.5. Page titles 22-26px, weight 550-600, tracking -0.01em.
- Data mono: Geist Mono / JetBrains Mono for timestamps, ids, token counts, event feed lines, code. 12-13px.
- Scale contrast ≥1.25 between hierarchy steps. Labels: 11px mono uppercase tracking +0.08em, text-low.

## Elevation & surfaces

Three layers, back to front:
1. Backdrop: bg-deep + drifting radial blobs (white 3-6% alpha, 40-60vw, 60-90s loops) + SVG grain at 2%.
2. Content: solid bg-raise panels, 1px line borders, radius 14px. NOT glass.
3. Chrome: glass (sidebar, command palette, overlays), radius 18px, border white/10, inner top highlight 1px white/6.

Nested cards are banned. Side-stripe accents are banned. Gradient text is banned.

## Motion

Cinematic but meaningful. ease-out-quint / expo only, no bounce.
- Page transitions: 240ms fade + 8px rise + slight blur-out.
- Panel entrances: staggered 40ms, 300ms.
- Live events: single 1.2s soft pulse ring on arrival; feed rows slide in 180ms.
- Idle: backdrop drift only. Nothing else moves while the user reads.
- Respect prefers-reduced-motion: kill drift and pulses.

## Components

- **GlassChrome**: sidebar, cmd-k palette, overlay panels. blur 24px, saturate 140%.
- **Panel**: solid surface, 1px border, 14px radius, 20px padding. Header row: 11px mono label + optional status dot.
- **StatusDot**: 6px, colored, pulse animation only when state is live-active.
- **FeedRow**: mono timestamp, kind pill, message. New rows flash white/6 background for 1s.
- **Kbd**: 11px mono in 1px-bordered rounded chip.
- Buttons: quiet (text-mid, hover text-hi + white/6 bg), primary (white/10 bg, text-hi), destructive (red text, red/10 bg on hover). No filled saturated buttons.

## Layout

App shell: fixed glass sidebar 232px left; content max-width none, 28px gutters; ⌘K palette centered overlay. Dashboard is an asymmetric grid (feed tall right rail or center hero, agent grid, CoS briefing wide) — never identical card grids. Vary panel heights and internal density for rhythm.

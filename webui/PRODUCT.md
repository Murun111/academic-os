# PRODUCT.md

## Product Purpose

Agentic OS frontend: the single control surface for a personal, local-first agent operating system. The backend (FastAPI at :7878) runs an agent runtime with human approval gates, a Chief of Staff loop, a memory spine over an Obsidian vault, a knowledge-base pipeline, an En/Mn translator learning engine, and life tools (calendar, money, inbox, browser). The frontend makes all of that observable and steerable in real time.

Design SERVES the product. This is an instrument you live in daily, not a marketing page.

## Register

product

## Users

One user: the owner-operator. Technical, runs everything locally, opens this many times a day to check what his agents did, approve gated actions, chat with models, inspect memory and traces, and correct translations. Uses it mostly at night on a MacBook in a dim room; ambient awareness matters as much as active use.

## Tone

Calm precision. The OS is competent and quiet; it never shouts. Live data feels like instrumentation, not gamification. Copy is terse, lowercase-comfortable, zero marketing voice. No mascots, no exclamation marks, no "🎉".

## Strategic principles

1. **Glass is architecture, not decoration.** The user explicitly chose a glassmorphic/spatial language. Frosted surfaces are reserved for structural chrome: the sidebar, the command palette, floating detail panels, toasts. Content areas sit on quiet solid surfaces so the glass reads as depth, not noise.
2. **Monochrome frost.** The world is tinted grayscale. Color exists only as status: green = running/ok, amber = pending/needs human, red = failed/blocked. When color appears, it means something changed.
3. **Live by default.** Events stream in over WebSocket. Motion is cinematic but tied to meaning: things pulse when they happen, drift when idle, and hold still when the user is reading.
4. **Everything reachable by keyboard.** Cmd+K is a first-class citizen: run agents, approve, search memory, jump anywhere.
5. **Mock-first, contract-true.** A typed API client mirrors the real endpoints (/api/*, /ws/events). Mock mode simulates the living system; one env var flips to the real backend.

## Anti-references

- Generic SaaS dashboards (hero metric cards, identical card grids, gradient text).
- Crypto-neon "AI" aesthetics, purple-to-cyan gradients, glow abuse.
- Notion/linear clones with no identity.
- Anything that looks like a template or would make someone say "AI made that."

## Scope (v1)

Dashboard (home: live event feed, agent grid, CoS briefing as heroes; approvals, health, life widgets secondary), Chat, Agents, Approvals, Memory, Traces, Chief of Staff, Translator, Wiki/KB. Dark only. No logo, no brand name in the UI.

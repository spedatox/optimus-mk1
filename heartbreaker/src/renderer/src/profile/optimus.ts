import type { AppProfile } from './types'

/**
 * ════════════════════════════════════════════════════════════════════════════
 *  BRANDING CONFIG — OPTIMUS MARK I.
 *  Forked from the Heartbreaker Stark-FUI shell and repurposed to drive the
 *  Optimus agent (Python port of Claude Code). This file drives the ENTIRE
 *  front-end: name, model number, colour, tagline, avatar, welcome prompts.
 * ════════════════════════════════════════════════════════════════════════════
 */
const profile: AppProfile = {
  name: 'OPTIMUS',
  modelNumber: 'Mark I',
  userName: 'Erol',
  tagline: 'Autonomous coding agent — your projects, built and maintained',
  avatarInitial: 'O',
  // JARVIS blue (matches the TUI theme: accent #00d4ff on #050a1e).
  accent: '#00d4ff',
  accentHover: '#5fe0ff',
  suggestedPrompts: [
    'Scaffold a new project from scratch',
    'Find and fix a bug across the codebase',
    'Add a feature and wire it into the app',
    'Review my recent changes and suggest improvements',
  ],
}

export default profile

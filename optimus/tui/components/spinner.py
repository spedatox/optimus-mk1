"""
optimus/tui/components/spinner.py

Port of: components/Spinner.tsx (SpinnerWithVerb),
         components/Spinner/SpinnerAnimationRow.tsx,
         components/Spinner/useStalledAnimation.ts,
         components/Spinner/utils.ts (getDefaultCharacters),
         constants/spinnerVerbs.ts.

The real streaming spinner line looks like:

    ✻ Pondering… (esc to interrupt · 32s · ↓ 1.2k tokens · thinking)

Behaviour mirrored from the source:
  - Glyph frames: ['·','✢','*','✶','✻','✽'] (non-macOS variant), played
    forward then reversed (SPINNER_FRAMES = chars + reversed(chars)),
    advancing every 120 ms.
  - Verb: one random pick from SPINNER_VERBS per turn, shown with "…".
  - Glimmer: a bright highlight sweeps across the verb text; sweep direction
    is right-to-left except in 'requesting' mode; period = text width + 20
    columns, one step per 200 ms (50 ms when requesting).
  - Status parts appear inside "(...)" after the verb, gated left-to-right by
    available width: suffix ("esc to interrupt"), elapsed timer, token count.
    Timer+tokens only show when verbose or elapsed > 30 s
    (SHOW_TOKENS_AFTER_MS).
  - Token counter animates smoothly toward chars/4 (increment 3 / 15% / 50
    per tick depending on gap).
  - Stall: when no new output chars for 3 s and no tool is running, the line
    fades to the error colour over 2 s (useStalledAnimation).
  - Thinking status: shows "thinking" while a thinking block streams; after it
    ends shows "thought for Ns" for 2 s (minimum 2 s display of each state).

Omitted (multi-agent / SaaS-only — documented in PORTING_NOTES.md):
teammate spinner tree, brief-mode spinner, task list panel, growthbook gates.
"""
from __future__ import annotations

import random
import sys
import time as _time
from typing import Optional

from textual.widgets import Static

# ---------------------------------------------------------------------------
# Constants — constants/spinnerVerbs.ts and Spinner/utils.ts
# ---------------------------------------------------------------------------

SPINNER_VERBS: list[str] = [
    'Accomplishing', 'Actioning', 'Actualizing', 'Architecting', 'Baking',
    'Beaming', "Beboppin'", 'Befuddling', 'Billowing', 'Blanching',
    'Bloviating', 'Boogieing', 'Boondoggling', 'Booping', 'Bootstrapping',
    'Brewing', 'Bunning', 'Burrowing', 'Calculating', 'Canoodling',
    'Caramelizing', 'Cascading', 'Catapulting', 'Cerebrating', 'Channeling',
    'Channelling', 'Choreographing', 'Churning', 'Clauding', 'Coalescing',
    'Cogitating', 'Combobulating', 'Composing', 'Computing', 'Concocting',
    'Considering', 'Contemplating', 'Cooking', 'Crafting', 'Creating',
    'Crunching', 'Crystallizing', 'Cultivating', 'Deciphering',
    'Deliberating', 'Determining', 'Dilly-dallying', 'Discombobulating',
    'Doing', 'Doodling', 'Drizzling', 'Ebbing', 'Effecting', 'Elucidating',
    'Embellishing', 'Enchanting', 'Envisioning', 'Evaporating', 'Fermenting',
    'Fiddle-faddling', 'Finagling', 'Flambéing', 'Flibbertigibbeting',
    'Flowing', 'Flummoxing', 'Fluttering', 'Forging', 'Forming',
    'Frolicking', 'Frosting', 'Gallivanting', 'Galloping', 'Garnishing',
    'Generating', 'Gesticulating', 'Germinating', 'Gitifying', 'Grooving',
    'Gusting', 'Harmonizing', 'Hashing', 'Hatching', 'Herding', 'Honking',
    'Hullaballooing', 'Hyperspacing', 'Ideating', 'Imagining', 'Improvising',
    'Incubating', 'Inferring', 'Infusing', 'Ionizing', 'Jitterbugging',
    'Julienning', 'Kneading', 'Leavening', 'Levitating', 'Lollygagging',
    'Manifesting', 'Marinating', 'Meandering', 'Metamorphosing', 'Misting',
    'Moonwalking', 'Moseying', 'Mulling', 'Mustering', 'Musing',
    'Nebulizing', 'Nesting', 'Newspapering', 'Noodling', 'Nucleating',
    'Orbiting', 'Orchestrating', 'Osmosing', 'Perambulating', 'Percolating',
    'Perusing', 'Philosophising', 'Photosynthesizing', 'Pollinating',
    'Pondering', 'Pontificating', 'Pouncing', 'Precipitating',
    'Prestidigitating', 'Processing', 'Proofing', 'Propagating', 'Puttering',
    'Puzzling', 'Quantumizing', 'Razzle-dazzling', 'Razzmatazzing',
    'Recombobulating', 'Reticulating', 'Roosting', 'Ruminating', 'Sautéing',
    'Scampering', 'Schlepping', 'Scurrying', 'Seasoning', 'Shenaniganing',
    'Shimmying', 'Simmering', 'Skedaddling', 'Sketching', 'Slithering',
    'Smooshing', 'Sock-hopping', 'Spelunking', 'Spinning', 'Sprouting',
    'Stewing', 'Sublimating', 'Swirling', 'Swooping', 'Symbioting',
    'Synthesizing', 'Tempering', 'Thinking', 'Thundering', 'Tinkering',
    'Tomfoolering', 'Topsy-turvying', 'Transfiguring', 'Transmuting',
    'Twisting', 'Undulating', 'Unfurling', 'Unravelling', 'Vibing',
    'Waddling', 'Wandering', 'Warping', 'Whatchamacalliting', 'Whirlpooling',
    'Whirring', 'Whisking', 'Wibbling', 'Working', 'Wrangling', 'Zesting',
    'Zigzagging',
]


def get_default_characters() -> list[str]:
    """Spinner/utils.ts getDefaultCharacters — platform-dependent glyph set."""
    if sys.platform == "darwin":
        return ['·', '✢', '✳', '✶', '✻', '✽']
    return ['·', '✢', '*', '✶', '✻', '✽']


_CHARS = get_default_characters()
# Spinner.tsx: SPINNER_FRAMES = [...chars, ...reversed(chars)]
SPINNER_FRAMES: list[str] = _CHARS + list(reversed(_CHARS))

SHOW_TOKENS_AFTER_MS = 30_000
FRAME_MS = 120            # glyph advance interval
TICK_S = 0.05             # 50 ms animation clock (useAnimationFrame(50))
GLIMMER_SPEED_MS = 200    # non-requesting glimmer step

# Dark-theme colours (utils/theme.ts darkTheme)
_CLAUDE = (215, 119, 87)          # claude
_CLAUDE_SHIMMER = (235, 159, 127)  # claudeShimmer
_ERROR = (255, 107, 128)           # error
_INACTIVE = "#999999"


def interpolate_color(c1: tuple, c2: tuple, t: float) -> tuple:
    """Spinner/utils.ts interpolateColor."""
    return (
        round(c1[0] + (c2[0] - c1[0]) * t),
        round(c1[1] + (c2[1] - c1[1]) * t),
        round(c1[2] + (c2[2] - c1[2]) * t),
    )


def _hex(c: tuple) -> str:
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


def format_duration(ms: float) -> str:
    """utils/format.ts formatDuration (mostSignificantOnly behaviour for the
    spinner line: seconds under a minute, then Xm Ys, then Xh Ym)."""
    if ms < 60_000:
        if ms <= 0:
            return "0s"
        return f"{int(ms // 1000)}s"
    minutes = int(ms // 60_000)
    seconds = int((ms % 60_000) // 1000)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes}m"


def format_token_count(n: int) -> str:
    """utils/format.ts formatNumber+formatTokens: '1321'→'1.3k', '900'→'900',
    '1000'→'1k' (trailing .0 stripped)."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        s = f"{n / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{s}k"
    s = f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".")
    return f"{s}m"


# ---------------------------------------------------------------------------
# SpinnerLine — the animated status line shown while a turn is streaming
# ---------------------------------------------------------------------------

class SpinnerLine(Static):
    """
    ✻ Pondering… (esc to interrupt · 32s · ↓ 1.2k tokens · thinking)

    Drive from the query loop:
        spinner.start()                      on turn start
        spinner.add_response_chars(len(t))   per stream_delta
        spinner.set_active_tools(True/False) around tool execution
        spinner.set_thinking(True/False)     around thinking blocks
        spinner.stop()                       on turn end (parent removes it)
    """

    DEFAULT_CSS = """
    SpinnerLine {
        height: 1;
        margin: 1 0 0 0;
        padding: 0;
        background: #1a1a1a;
    }
    """

    def __init__(
        self,
        verb: Optional[str] = None,
        suffix: str = "esc to interrupt",
        verbose: bool = False,
        **kwargs,
    ) -> None:
        super().__init__("", **kwargs)
        # Spinner.tsx picks the verb once on mount (useState initializer)
        self._verb = verb or random.choice(SPINNER_VERBS)
        self._suffix = suffix
        self._verbose = verbose
        self._mode = "responding"       # 'requesting' | 'responding' | 'tool-use' | 'thinking'

        self._start_time = _time.monotonic()
        self._response_length = 0       # streamed chars this turn
        self._has_active_tools = False

        # Token counter animation state (SpinnerAnimationRow tokenCounterRef)
        self._displayed_length = 0

        # Stall state (useStalledAnimation)
        self._last_token_time = 0.0     # relative to start
        self._stalled_intensity = 0.0

        # Thinking status: 'thinking' | float (duration ms) | None,
        # with the 2 s minimum-display rule from Spinner.tsx.
        self._thinking_status: object = None
        self._thinking_start: Optional[float] = None
        self._thinking_clear_at: Optional[float] = None

        self._timer = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._timer = self.set_interval(TICK_S, self._tick)
        self._tick()

    def on_unmount(self) -> None:
        self.stop()

    def stop(self) -> None:
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None

    # ------------------------------------------------------------------
    # Inputs from the query loop
    # ------------------------------------------------------------------

    def add_response_chars(self, n: int) -> None:
        if n <= 0:
            return
        self._response_length += n
        # Reset stall timer on new tokens
        self._last_token_time = self._elapsed_ms()
        self._stalled_intensity = 0.0

    def set_active_tools(self, active: bool) -> None:
        self._has_active_tools = active
        self._mode = "tool-use" if active else "responding"

    def set_thinking(self, thinking: bool) -> None:
        now = self._elapsed_ms()
        if thinking:
            if self._thinking_start is None:
                self._thinking_start = now
                self._thinking_status = "thinking"
                self._thinking_clear_at = None
            self._mode = "thinking"
        elif self._thinking_start is not None:
            duration = now - self._thinking_start
            # Show 'thinking' for at least 2 s, then the duration for 2 s
            remaining = max(0.0, 2000.0 - duration)
            self._thinking_status = duration
            self._thinking_clear_at = now + remaining + 2000.0
            self._thinking_start = None
            self._mode = "responding"

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    # ------------------------------------------------------------------
    # Animation tick
    # ------------------------------------------------------------------

    def _elapsed_ms(self) -> float:
        return (_time.monotonic() - self._start_time) * 1000.0

    def _tick(self) -> None:
        t = self._elapsed_ms()

        # Expire the "thought for Ns" display window
        if self._thinking_clear_at is not None and t >= self._thinking_clear_at:
            self._thinking_status = None
            self._thinking_clear_at = None

        # === Token counter animation ===
        gap = self._response_length - self._displayed_length
        if gap > 0:
            if gap < 70:
                inc = 3
            elif gap < 200:
                inc = max(8, int(gap * 0.15) + 1)
            else:
                inc = 50
            self._displayed_length = min(self._displayed_length + inc, self._response_length)

        # === Stall intensity (useStalledAnimation) ===
        if self._has_active_tools:
            since_token = 0.0
            self._last_token_time = t
        elif self._response_length > 0:
            since_token = t - self._last_token_time
        else:
            since_token = t
        is_stalled = since_token > 3000 and not self._has_active_tools
        target = min((since_token - 3000) / 2000, 1.0) if is_stalled else 0.0
        # smooth toward target: current += diff * 0.1 per 50 ms step
        diff = target - self._stalled_intensity
        if abs(diff) < 0.01:
            self._stalled_intensity = target
        else:
            self._stalled_intensity += diff * 0.1

        self.update(self._render_line(t))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_line(self, t: float) -> str:
        frame = int(t // FRAME_MS) % len(SPINNER_FRAMES)
        glyph = SPINNER_FRAMES[frame]

        # Colour: claude orange, faded to error red by stall intensity
        base = interpolate_color(_CLAUDE, _ERROR, self._stalled_intensity)
        base_hex = _hex(base)

        message = f"{self._verb}…"

        # === Glimmer sweep (GlimmerMessage) ===
        # cycle = width + 20 cols; step every 200 ms; right-to-left except
        # 'requesting'; suppressed when stalled.
        if self._stalled_intensity > 0:
            message_markup = f"[bold {base_hex}]{message}[/bold {base_hex}]"
        else:
            width = len(message)
            cycle_len = width + 20
            speed = 50 if self._mode == "requesting" else GLIMMER_SPEED_MS
            pos = int(t // speed)
            if self._mode == "requesting":
                glimmer = (pos % cycle_len) - 10
            else:
                glimmer = width + 10 - (pos % cycle_len)
            shimmer_hex = _hex(_CLAUDE_SHIMMER)
            parts: list[str] = []
            for i, ch in enumerate(message):
                # Highlight the glimmer char and immediate neighbours
                if abs(i - glimmer) <= 1:
                    parts.append(f"[bold {shimmer_hex}]{ch}[/bold {shimmer_hex}]")
                else:
                    parts.append(f"[bold {base_hex}]{ch}[/bold {base_hex}]")
            message_markup = "".join(parts)

        # === Status parts, gated in source order: suffix, timer, tokens, thinking ===
        status_parts: list[str] = []
        if self._suffix:
            status_parts.append(self._suffix)

        wants_timer_tokens = self._verbose or t > SHOW_TOKENS_AFTER_MS
        if wants_timer_tokens:
            status_parts.append(format_duration(t))
            tokens = round(self._displayed_length / 4)
            if tokens > 0:
                status_parts.append(f"↓ {format_token_count(tokens)} tokens")

        if self._thinking_status == "thinking":
            status_parts.append("thinking")
        elif isinstance(self._thinking_status, (int, float)):
            secs = max(1, round(self._thinking_status / 1000))
            status_parts.append(f"thought for {secs}s")

        status = ""
        if status_parts:
            joined = " · ".join(status_parts)
            status = f" [{_INACTIVE}]({joined})[/{_INACTIVE}]"

        return f"[bold {base_hex}]{glyph}[/bold {base_hex}] {message_markup}{status}"


# ---------------------------------------------------------------------------
# INTERRUPTED — components/InterruptedByUser.tsx (external-build branch)
# ---------------------------------------------------------------------------

INTERRUPTED_MARKUP = "[#999999]Interrupted · What should Optimus do instead?[/#999999]"

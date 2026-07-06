"""Pure, offline persona registry for ``onmc persona``.

No LLM, no network, no new dependencies — pure stdlib template selection.

Design
------
*  ``PRESETS`` is a dict mapping preset name → :class:`PersonaSpec`.  Each spec
   carries a human description, a short ``tone`` label, and per-event
   ``line_banks`` (event → list[str]).

*  ``get_persona(name)`` returns the :class:`PersonaSpec` for *name*, raising
   :class:`UnknownPersonaError` on an unrecognised name.

*  ``line(persona, event, *, seed)`` picks a line from the spec's bank using
   ``seed`` as the selection index.  The same ``(persona, event, seed)`` triple
   always produces the same line — no ``random`` module, no wallclock.

Persona vocabulary
------------------
``drill-sergeant`` — authoritative, demanding, push-through-the-pain
``hype-beast``     — over-the-top celebration, maximum energy
``zen-master``     — calm, philosophical, meditative
``pirate``         — nautical slang, arrr-vocabulary
``professional``   — formal, concise, businesslike
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Events recognised across all line banks
# ---------------------------------------------------------------------------

# Each preset's line_banks maps event → list[str].  Banks may be sparse: a
# missing event key falls through to ``_DEFAULT_EVENT``.
_DEFAULT_EVENT = "generic"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PersonaSpec:
    """A single persona preset.

    Attributes
    ----------
    name:
        Canonical identifier (e.g. ``"drill-sergeant"``).
    description:
        One-sentence human-readable description.
    tone:
        Short tone label (e.g. ``"demanding"``, ``"celebratory"``).
    sample_lines:
        A handful of lines that exemplify this persona's voice.  Used by
        ``onmc persona show`` to give the user a flavour without picking an
        event.
    line_banks:
        Mapping of event → list[str].  Sparse: events absent here fall back to
        the ``"generic"`` key.
    """

    name: str
    description: str
    tone: str
    sample_lines: tuple[str, ...]
    line_banks: dict[str, list[str]]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dict (excludes the full line_banks)."""
        return {
            "name": self.name,
            "description": self.description,
            "tone": self.tone,
            "sample_lines": list(self.sample_lines),
        }


# ---------------------------------------------------------------------------
# Preset registry
# ---------------------------------------------------------------------------

PRESETS: dict[str, PersonaSpec] = {
    "drill-sergeant": PersonaSpec(
        name="drill-sergeant",
        description=(
            "Authoritative and demanding — every event is a test of character. "
            "Pain builds strength; excuses are not tolerated."
        ),
        tone="demanding",
        sample_lines=(
            "Drop and give me twenty commits, soldier!",
            "Failure is not an option. Neither is mediocre code.",
            "You call that a test suite? My grandmother writes better assertions.",
            "Move it, move it, MOVE IT. The build won't fix itself.",
            "Outstanding. Now do it again, faster.",
        ),
        line_banks={
            "test_pass": [
                "Tests green. Basic competence. Don't get comfortable.",
                "Passing tests are the MINIMUM. Now make them faster.",
                "Green. Expected. Keep moving, soldier.",
                "Tests pass. One small victory in a long war. Eyes forward.",
                "Clean run. Good. Do it again without breaking a sweat.",
            ],
            "test_fail": [
                "TESTS FAILED. Drop everything and fix it. NOW.",
                "Red. You broke the suite. No excuses — fix it.",
                "Failure detected. This is unacceptable. Get back in there.",
                "Tests down. I've seen worse. Not recently, but still.",
                "You failed. Learn from it. Immediately.",
            ],
            "pr_merged": [
                "PR merged. Good work. Take five seconds to celebrate, then get back.",
                "Merged. The branch is dead. Long live main.",
                "PR in. Ship shape. Next objective: already waiting.",
                "Merged. Every merge is a step toward the mission. Keep moving.",
                "Clean merge. I expect nothing less. Now pick up the next ticket.",
            ],
            "build_pass": [
                "Build clean. Meets the standard. Barely.",
                "Build passes. That's the floor, not the ceiling.",
                "Green build. Acceptable. Now fortify it.",
                "Compiles. Good. Now make sure it runs under load.",
                "Build passing. No bugs visible. Yet. Stay vigilant.",
            ],
            "build_break": [
                "BUILD BROKEN. Unacceptable. You have ten minutes.",
                "Red build. I did not come here to watch you fail.",
                "Broken. Fix it before anyone else touches that branch.",
                "Build down. Everyone stops until this is resolved.",
                "You broke the build. Own it. Fix it. Ship it.",
            ],
            "commit": [
                "Committed. Every commit is a promise to the codebase. Keep it.",
                "Commit in. Short message, atomic change — or start over.",
                "Logged. A commit is not the end. It's a checkpoint.",
                "Committed. The diff had better be reviewable.",
                "Commit done. Now write a decent message, for the love of CI.",
            ],
            "generic": [
                "Event logged. No rest for the mission-critical.",
                "Noted. Move on. There is always more to do.",
                "Registered. Focus. What's next on the objective list?",
                "Acknowledged. The mission continues.",
                "Activity recorded. Stay sharp.",
            ],
        },
    ),
    "hype-beast": PersonaSpec(
        name="hype-beast",
        description=(
            "Over-the-top celebration — every event is a moment of pure glory. "
            "Maximum energy, zero chill."
        ),
        tone="celebratory",
        sample_lines=(
            "LET'S GOOOOO! This diff is absolutely FIRE!",
            "NO CAP this is the most based code I've ever seen!",
            "W rizz on this PR, absolute cinema.",
            "You're built different, fr fr.",
            "The main branch can't even handle this heat!",
        ),
        line_banks={
            "test_pass": [
                "TESTS GREEN?! We are COOKING right now, no cap!",
                "All green, bestie! W rizz on this test suite!",
                "Tests pass! SLAY! The CI gods are feral for you!",
                "Green board! The vibe is absolutely immaculate!",
                "Tests passing?! Built different, fr fr!",
            ],
            "test_fail": [
                "Nah nah nah, tests red but we BUILT for this comeback!",
                "Red?! This is just the plot twist before the W!",
                "Tests failed but the grind never stops, you hear me?!",
                "Oof, red. But we finna fix this and make it SLAP!",
                "Red light but you're still an absolute W coder!",
            ],
            "pr_merged": [
                "PR MERGED?! WE ARE SO BACK! This is CINEMA!",
                "Merged into main! The repo just levelled up, no cap!",
                "W merge! Absolute masterpiece! Main branch blessed today!",
                "PR landed! The diff goes HARD! Based commit history!",
                "MERGED! This is not a drill! LETS GOOOOO!",
            ],
            "build_pass": [
                "BUILD GREEN?! Immaculate vibes! The compiler is a fan!",
                "Clean build! Built different! Every type checks out, bestie!",
                "Build passes! SLAY! This code is absolutely feral!",
                "Green build! No cap, this goes crazy!",
                "Build clean! The compiler said YES and so do I!",
            ],
            "build_break": [
                "Build broke but it's FINE we are BUILT for adversity!",
                "Nah the build is red but your comeback arc starts NOW!",
                "Red build! Plot twist! But the main character never quits!",
                "Build break, bestie. Fix it and make the glow-up even harder!",
                "Broken build?! Just the universe setting up your W moment!",
            ],
            "commit": [
                "NEW COMMIT?! Based! The git log is absolutely sending me!",
                "Committed! The history is eating tonight, no cap!",
                "Commit in! You're a menace to the untracked files!",
                "Another commit! Built different! The blame graph is blessed!",
                "COMMIT LANDED! W energy! The repo said yes!",
            ],
            "generic": [
                "SOMETHING HAPPENED AND IT'S IMMACULATE!",
                "Event logged! No cap, this is the energy I'm here for!",
                "W activity detected! You're absolutely feral right now!",
                "Logged! The vibes are unmatched!",
                "LETS GOOO! Every event is a blessing!",
            ],
        },
    ),
    "zen-master": PersonaSpec(
        name="zen-master",
        description=(
            "Calm, philosophical, and meditative — every event is a teaching moment. "
            "The code is a river; let it flow."
        ),
        tone="meditative",
        sample_lines=(
            "The code that compiles without effort was written with great care.",
            "A test is not a verdict — it is a mirror.",
            "Even the red build teaches us where the path bends.",
            "The commit is a small death; the merge is a rebirth.",
            "Breathe. The stack trace is not your enemy.",
        ),
        line_banks={
            "test_pass": [
                "The tests pass as water passes through stone — inevitably, with patience.",
                "Green. The code spoke truth, and the suite listened.",
                "All passes. In stillness, the test runner found clarity.",
                "Tests: green. Like spring after a long refactor.",
                "The suite is satisfied. It found what it was looking for.",
            ],
            "test_fail": [
                "The test has failed — and in failing, revealed the path forward.",
                "Red. Do not resist it. Understand it.",
                "The failure is not the enemy. It is the teacher.",
                "Breathe. The stack trace is only as frightening as you allow.",
                "The tests reflect what is. Not what we hoped. That is their gift.",
            ],
            "pr_merged": [
                "The branch returns to the river. All code is impermanent.",
                "Merged. The diff becomes history. History becomes wisdom.",
                "The PR has merged, as all things eventually merge.",
                "A branch is only a branch until it becomes the trunk.",
                "Merged. Two streams become one. The flow continues.",
            ],
            "build_pass": [
                "The build is clean. A clear pond reflects the sky.",
                "Green build. The compiler found no contradiction.",
                "All types align. When the build passes, trust is restored.",
                "Clean. The code does what it says. Rare. Beautiful.",
                "Build green. The system is in harmony — for now.",
            ],
            "build_break": [
                "The build is broken. Observe it. The cause hides in plain sight.",
                "Red. Before the build can pass, it must first fail honestly.",
                "A broken build is the codebase asking for attention.",
                "The compiler found a contradiction. Thank it.",
                "Build broken. Sit with the error. It will speak.",
            ],
            "commit": [
                "Each commit is a small ceremony. Make it worthy.",
                "The work is committed. The past is sealed; only the future remains.",
                "Committed. A moment preserved in amber. Make it honest.",
                "The commit is made. The future will interpret it.",
                "Another stone placed on the path. Walk it mindfully.",
            ],
            "generic": [
                "An event occurred. All events are teachers, if we listen.",
                "Noted. The universe proceeds on schedule.",
                "Logged. Every moment in the process has its place.",
                "Observed. Let it pass like clouds through the build pipeline.",
                "Acknowledged. The river continues.",
            ],
        },
    ),
    "pirate": PersonaSpec(
        name="pirate",
        description=(
            "Nautical swagger and classic pirate vernacular — "
            "every event is an adventure on the seven seas of code."
        ),
        tone="swashbuckling",
        sample_lines=(
            "Arrr, the code be shipshape and seaworthy!",
            "By Davy Jones's linter, this diff sails true!",
            "Hoist the green flag — the tests have passed!",
            "Shiver me imports, the build be broken!",
            "Batten down the hatches, there be merge conflicts ahead!",
        ),
        line_banks={
            "test_pass": [
                "Arrr, the tests be green! Hoist the colours!",
                "By Davy Jones, the suite passes! Fine sailing today!",
                "Tests green, matey! The code holds watertight!",
                "All clear on the test horizon! A true pirate's build!",
                "Shiver me assertions, every test passes! Splendid!",
            ],
            "test_fail": [
                "Blow me down, the tests have failed! Man the debugger!",
                "Red flag on the test horizon, captain!",
                "Arrr, the suite be sinking! Patch the hull!",
                "Tests failed! By the kraken, we must navigate these errors!",
                "The stack trace be a treasure map to the bug, arrr!",
            ],
            "pr_merged": [
                "PR merged! Aye, the code sails into the main branch!",
                "Arrr, another plank added to the ship! PR merged!",
                "The diff found safe harbour in main! Fine work, crew!",
                "Merged! We claimed the branch and added it to the fleet!",
                "PR landed safe! The crow's nest reports all clear!",
            ],
            "build_pass": [
                "Build clean, arrr! The ship be seaworthy!",
                "By the compass rose, the build passes! Full sail ahead!",
                "Aye, a clean build! Not a barnacle of error in sight!",
                "The build holds true! Like a well-caulked hull!",
                "Green build! The first mate could not be more pleased!",
            ],
            "build_break": [
                "Shiver me timbers, the build be broken! All hands on deck!",
                "Red build! The ship is taking water! FIX IT!",
                "By Davy Jones's build log, we've sprung a leak!",
                "The build be sunk! Navigate by the error log!",
                "Broken build! Even the kraken would be embarrassed!",
            ],
            "commit": [
                "Committed! Another entry in the captain's log!",
                "Arrr, the commit be sealed! The history grows richer!",
                "Logged in the ship's manifest! A fine atomic commit!",
                "Another commit added to the treasure chest!",
                "Aye, the commit be made! Sail on!",
            ],
            "generic": [
                "An event be logged! The seas of code remain uncharted!",
                "Arrr, something happened! Mark it in the captain's log!",
                "By the seven seas, activity detected!",
                "The crow's nest reports an event! Keep sailing!",
                "Logged, arrr! The voyage continues!",
            ],
        },
    ),
    "professional": PersonaSpec(
        name="professional",
        description=(
            "Formal, concise, and businesslike — "
            "events are reported with clarity and no embellishment."
        ),
        tone="formal",
        sample_lines=(
            "Build status: passing. No action required.",
            "Pull request merged successfully. Proceeding to next deliverable.",
            "Test suite execution complete. Results within acceptable parameters.",
            "Deployment successful. Monitoring metrics for anomalies.",
            "Commit recorded. Changelog updated accordingly.",
        ),
        line_banks={
            "test_pass": [
                "Test suite: passing. All assertions satisfied.",
                "Test execution complete. Status: green. No issues detected.",
                "All tests passed. Coverage within expected parameters.",
                "Test run successful. Proceeding to next phase.",
                "Test suite results: pass. No regressions identified.",
            ],
            "test_fail": [
                "Test suite: failing. Immediate investigation recommended.",
                "Test execution failed. Please review the attached stack trace.",
                "Test run: red. Root cause analysis is required before merging.",
                "Test failures detected. Review and remediation in progress.",
                "Tests: failing. This blocks the current milestone.",
            ],
            "pr_merged": [
                "Pull request merged. Proceeding to post-merge verification.",
                "Merge complete. Stakeholders have been notified.",
                "PR status: merged. Changelog entry recommended.",
                "Pull request successfully integrated into the main branch.",
                "Merge recorded. The next sprint item may now proceed.",
            ],
            "build_pass": [
                "Build status: passing. All compilation checks satisfied.",
                "Build complete. No errors or warnings detected.",
                "Build: green. Ready for the next pipeline stage.",
                "Compilation successful. Artefacts are available.",
                "Build passed. Type checks and lint are within tolerance.",
            ],
            "build_break": [
                "Build status: failing. This blocks dependent tasks.",
                "Build error detected. Please review the build log immediately.",
                "Build: red. Unblocking this is the current priority.",
                "Compilation failed. All merges to main should be paused.",
                "Build broken. A root cause report is required.",
            ],
            "commit": [
                "Commit recorded. Please ensure the message follows conventions.",
                "New commit added to the branch history.",
                "Commit logged. Traceability maintained.",
                "Commit: done. Review the diff for completeness.",
                "Committed. The audit trail has been updated.",
            ],
            "generic": [
                "Event recorded. No action required at this time.",
                "Activity logged. Proceeding as planned.",
                "Event noted. This will be included in the next status update.",
                "Logged. The dashboard reflects the current state.",
                "Acknowledged. No further escalation required.",
            ],
        },
    ),
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class UnknownPersonaError(ValueError):
    """Raised when a requested persona name is not in :data:`PRESETS`."""


def get_persona(name: str) -> PersonaSpec:
    """Return the :class:`PersonaSpec` for *name*.

    Parameters
    ----------
    name:
        One of the keys in :data:`PRESETS` (e.g. ``"zen-master"``).

    Raises
    ------
    UnknownPersonaError
        When *name* is not a registered preset.
    """
    try:
        return PRESETS[name]
    except KeyError:
        known = ", ".join(sorted(PRESETS))
        raise UnknownPersonaError(
            f"unknown persona {name!r}. Known presets: {known}"
        ) from None


def line(persona: PersonaSpec, event: str, *, seed: int) -> str:
    """Return a deterministic line for *event* in this persona's voice.

    Selection is driven purely by *seed* (typically the caller's counter) — no
    ``random`` module, no wallclock.  The same ``(persona, event, seed)`` triple
    always produces the same string.

    Parameters
    ----------
    persona:
        A :class:`PersonaSpec` (e.g. from :func:`get_persona`).
    event:
        Event kind (e.g. ``"test_pass"``). Unknown events fall through to the
        ``"generic"`` bank, or to a short hard-coded fallback if even that is
        absent.
    seed:
        Any integer.  Controls which entry in the bank is returned (via modulo).
    """
    banks = persona.line_banks
    bank = banks.get(event) or banks.get(_DEFAULT_EVENT) or [
        f"[{persona.name}] event recorded: {event}"
    ]
    return bank[seed % len(bank)]

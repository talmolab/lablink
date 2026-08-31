# Shared settings for every lablink CLI doc recording.
# Sourced by the numbered tapes in this directory — change look-and-feel here.
#
# ---------------------------------------------------------------------------
# HOW TO WAIT (learned the hard way — all three cases were reproduced)
#
#   Wait+Screen  matches the whole visible screen. It BREAKS as soon as the
#                command's output scrolls past the viewport: the scrape gets
#                stuck on the first visible line and never matches, so the
#                tape blocks for the full WaitTimeout. Only safe for a
#                full-screen TUI (the wizard), which never scrolls.
#
#   Wait+Line    matches the current line. Reliable for a BLOCKING PROMPT,
#                because the prompt stays the current line until answered.
#                It MISSES transient lines — a "Deployment complete!" that
#                more output scrolls past is frequently never seen.
#
#   Wait+Line /^\$$/   waits for the bare `$ ` prompt to come back, i.e. the
#                command finished. This is the anchor for anything whose
#                duration varies (tofu apply, the health poll) and the only
#                one that survives arbitrary scrolling.
#
# So: TUI screen -> +Screen. Blocking prompt -> +Line on the prompt text.
# Anything else -> +Line on the prompt returning. Never +Line on a line that
# later output will scroll past.
#
# EVERY "prompt returning" anchor depends on PS1 being exactly what the tape
# set. It is not enough to export it: Git Bash, and any distro whose bashrc
# sets PROMPT_COMMAND, REBUILD PS1 from that hook on every prompt and discard
# the tape's value. The anchor then can never match and the tape hangs for the
# full WaitTimeout. Every tape's Hide block therefore does
#   Type `unset PROMPT_COMMAND` Enter
# BEFORE setting PS1. macOS bash sets no PROMPT_COMMAND, which is why this
# only ever surfaced on the Windows box recording clip 03.
# ---------------------------------------------------------------------------
#
# Two more VHS gotchas:
#   * Every path in a tape MUST be quoted. VHS 0.11's lexer splits bare paths
#     on digits and hyphens, so `Output cli-01-configure.mp4` is a parse error.
#   * `Type` cannot contain escaped double quotes. Use backticks for a string
#     that needs them, or put the command in a script file.
#
# AWS credentials are inherited from the shell that launches vhs — run
# `aws sso login` before recording. Never type credentials inside a tape.

Set Shell "bash"
Set FontSize 18
Set Width 1400
Set Height 900
Set Padding 20
Set TypingSpeed 60ms
Set Framerate 30
Set Theme "Catppuccin Mocha"

# Long enough for `tofu apply` plus the first-boot health poll.
Set WaitTimeout 20m

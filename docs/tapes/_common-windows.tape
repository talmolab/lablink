# Shared settings for the PowerShell recordings — the Windows twin of
# _common.tape. Look-and-feel is deliberately identical so a Windows clip and
# a macOS clip sit side by side in the docs without looking like two projects.
#
# WHY THIS FILE EXISTS
#
# `Set Shell "bash"` hangs on native Windows: vhs prints its directives as it
# runs them, so the tape gets as far as `Output ...` and then sits until
# WaitTimeout, with the shell never coming up and not one `Type` executed. A
# tape with no `Set Shell` line renders fine on the same box, which is how it
# was isolated. See _common.tape's header for the full account, including the
# stale-ttyd effect that makes retests lie.
#
# So the Windows tapes drive PowerShell instead. Everything in the WAIT RULES
# section of _common.tape still applies unchanged — the prompt anchors, the
# scrolling trap, all of it. Read that file first; this one only covers what
# differs.
#
# THE PROMPT
#
# PowerShell has no PS1. The prompt is whatever a function named `prompt`
# returns, so the tapes do:
#
#   function prompt { 'box$ ' }
#
# Single quotes, not double: PowerShell interpolates `$` inside double quotes.
# Defining it in the tape's Hide block runs AFTER $PROFILE has loaded, so it
# overrides oh-my-posh and friends rather than being overridden by them —
# the same trap as bash's PROMPT_COMMAND, which is why the bash tapes unset
# that before setting PS1.
#
# DOCKER
#
# Docker Desktop serves native Windows and WSL2 from one engine, so
# `docker run` here is the same daemon either way. The client image is a
# Linux container; Docker Desktop must be in Linux-containers mode (its
# default). Windows-containers mode cannot run it at all.

Set Shell "powershell"
Set FontSize 18
Set Width 1400
Set Height 900
Set Padding 20
Set TypingSpeed 60ms
Set Framerate 30
Set Theme "Catppuccin Mocha"

# Long enough for a cold client-image pull on a slow link.
Set WaitTimeout 20m

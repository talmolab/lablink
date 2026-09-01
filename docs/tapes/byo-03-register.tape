# docs/cli/byo-clients.md — Step 4: Register each box (reverse_tunnel)
#
# *** THIS TAPE RUNS ON THE BOX, NOT ON THE ALLOCATOR HOST. ***
# That is the whole reason it is a separate clip: the doc says "run this on
# the machine you're adding", and a recording made on the allocator host
# would quietly contradict its own instructions. Record it by running
# `scripts/record-docs.sh --box <allocator-url> <token>` on the second
# machine, then copy the .mp4 back into docs/assets/videos/.
#
# PS1 is the same bare "$ " as every other clip. The change of machine is
# carried by the doc's caption and by what the commands themselves show,
# not by dressing the prompt up: a "box$ " prompt no reader will ever see
# on their own machine looks like a typo in a copy-pasteable transcript.
#
# The deployment being registered against is manual.connectivity:
# reverse_tunnel, so the command carries --tunnel: the box dials OUT to the
# allocator and holds one connection open. Nothing dials in to it, which is
# why the auto-detected values below report no LAN IP — there is no inbound
# address worth having.
#
# The register command line is not in this file: it carries a per-run
# allocator URL and register token, so --box writes it into the gitignored
# .byo-register.tape that the Source below pulls in. That Source is
# deliberately OUTSIDE a Hide block — the typed command IS the content of
# this clip, and the token in it dies with the stack clip 04 destroys.
#
# --box pulls the client image before this tape starts. It is a KasmVNC
# desktop image and on Apple Silicon it is amd64-under-emulation, so a cold
# pull is minutes of progress bar; the doc's caption says the pull was cut.

Source "_common.tape"
Output "../assets/videos/byo-03-register.mp4"

# Puts the recording venv's bin on PATH. Written per run by
# scripts/record-docs.sh because it is an absolute, machine-specific path.
# It carries its own Hide/Show: VHS 0.11 silently ignores a Source that
# appears INSIDE a Hide block — the sourced Type never executes and every
# `lablink …` records as "command not found", with nothing in the log to
# say why. Keep this Source at top level.
Source ".path.tape"

Hide
# `unset PROMPT_COMMAND` before PS1, not after: Git Bash (and any
# distro whose bashrc sets one) REBUILDS PS1 on every prompt from
# PROMPT_COMMAND, silently discarding the value set here. The tape
# then waits on a prompt regex that can never match and hangs for
# the full WaitTimeout. Cost a recording session on Windows to find.
Type `unset PROMPT_COMMAND` Enter
Type `export PS1="$ "` Enter
Type "clear" Enter
Show

Sleep 2s

# `lablink client register --allocator-url … --register-token … --tunnel`
Source ".byo-register.tape"
Sleep 1s
Enter

# Auto-detection (hostname, LAN IP, machine identity, GPU), the 0600
# ~/.lablink/client.env write, and the container start.
Wait+Line /^\$$/
Sleep 8s

# --- Confirm the box's own health ----------------------------------------
# `client doctor` is the box-side check: registration, container, and log
# shipper. `lablink status` is NOT run here — it reads the deployment
# config, which only exists on the allocator host, and that is where clip
# 04 shows this box landing in the pool.
Type "clear" Sleep 500ms Enter
Sleep 1s
Type "lablink client doctor" Sleep 500ms Enter
Wait+Line /^\$$/
Sleep 8s

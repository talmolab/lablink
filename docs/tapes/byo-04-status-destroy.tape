# docs/cli/byo-clients.md — Step 4 (confirm) and Tearing down
#
# Runs on the ALLOCATOR HOST, after the box has registered. Assumes
# byo-02-deploy.tape left a stack standing and that clip 03 was recorded on
# the box in between, so the pool is not empty — record-docs.sh enforces
# that ordering by blocking between the two.
#
# `lablink status` lives here rather than at the end of clip 03 because it
# reads the deployment config, which exists only on this machine. That
# split is the honest one: registering is a box-side act, confirming the
# pool is an allocator-side one.
#
# `destroy` under provider: manual has exactly one prompt — "Type 'yes' to
# tear down compose stack at <path>". There is no metrics-export question
# (that one belongs to the AWS destroy) and no second confirmation.
#
# Same 2x compression as clip 02: SLEEPS BELOW ARE WALL-CLOCK, on-screen
# duration is each value halved. Waits follow _common.tape — the destroy
# confirmation blocks (so +Line on its text is safe), everything else
# anchors on the shell prompt returning.

Source "_common.tape"
Output "../assets/videos/byo-04-status-destroy.mp4"

Set PlaybackSpeed 2
Set TypingSpeed 120ms

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

# --- Confirm the box landed in the pool ----------------------------------
# Under manual, status shows compose container health and the allocator's
# health endpoint — and no cost estimate, because the hardware is yours.
Sleep 2s
Type "lablink status" Sleep 1s Enter
Wait+Line /^\$$/
Sleep 30s

# --- Tearing down ---------------------------------------------------------
# Plain `destroy`, i.e. the Postgres volume is wiped. The doc's
# `--keep-data` variant is a flag on this same command, not a second flow,
# so it stays text-only rather than costing a clip.
Type "clear" Sleep 1s Enter
Sleep 2s
Type "lablink destroy" Sleep 1s Enter

Wait+Line /Type 'yes' to tear down/
Sleep 8s
Type "yes" Sleep 1s Enter

Wait+Line /^\$$/
Sleep 12s

# docs/cli/byo-clients.md — Step 4: Register each box (reverse_tunnel), Windows
#
# *** THIS TAPE RUNS ON THE BOX, NOT ON THE ALLOCATOR HOST. ***
# The PowerShell twin of byo-03-register.tape. record-docs.sh picks between
# them by `uname -s`, so `--box` is the same command on either platform.
#
# Same clip, same content, different shell. Keep the two in step: if the
# register flow changes, both need the edit. They are separate files rather
# than one parameterised tape because a vhs tape takes no arguments and
# `Output` must be a literal.
#
# The prompt is "box$ " here, as in the bash take, so the change of machine is
# visible on camera rather than merely asserted in the caption. PowerShell has
# no PS1 — see _common-windows.tape for why this is a `prompt` function and
# why it is defined here rather than in a profile.
#
# The register command line is not in this file: it carries a per-run
# allocator URL and register token, so --box writes it into the gitignored
# .byo-register.tape that the Source below pulls in. That Source is
# deliberately OUTSIDE a Hide block — the typed command IS the content of this
# clip, and the token in it dies with the stack clip 04 destroys.
#
# `lablink` resolves through PATH, which vhs inherits from the Git Bash shell
# that launched it; MSYS converts the POSIX PATH to Windows form on the way
# out to a native process, so the venv's Scripts\ directory is visible here.
# record-docs.sh has already checked that it resolves to the repo's own venv.

Source "_common-windows.tape"
Output "../assets/videos/byo-03-register.mp4"

Hide
Type `function prompt { 'box$ ' }` Enter
Type "clear" Enter
Show

Sleep 2s

# `lablink client register --allocator-url … --register-token … --tunnel`
Source ".byo-register.tape"
Sleep 1s
Enter

# Auto-detection (hostname, machine identity, GPU), the ~/.lablink/client.env
# write, and the container start. No LAN IP is reported: nothing dials in to a
# reverse-tunnel client, so it has no inbound address worth having.
Wait+Line /^box\$$/
Sleep 8s

# --- Confirm the box's own health ----------------------------------------
# `client doctor` is the box-side check: registration, container, and log
# shipper. `lablink status` is NOT run here — it reads the deployment config,
# which only exists on the allocator host, and that is where clip 04 shows
# this box landing in the pool.
Type "clear" Sleep 500ms Enter
Sleep 1s
Type "lablink client doctor" Sleep 500ms Enter
Wait+Line /^box\$$/
Sleep 8s

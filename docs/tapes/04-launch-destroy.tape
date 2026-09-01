# docs/cli/first-deployment.md — Steps 5-6: Launch a client VM, then Tear down
#
# *** THIS TAPE USES AND THEN DESTROYS REAL AWS RESOURCES. ***
# Assumes 03-deploy.tape just left an allocator running, so the two only make
# sense back to back and in that order; record-docs.sh enforces it.
#
# `client launch` and `destroy` both read the admin credentials 03 saved to
# the deployment dir (resolve_admin_credentials), so neither prompts for a
# password — nothing secret is typed in this tape.
#
# Same 4x compression as 03: ON-SCREEN DURATION IS EACH SLEEP DIVIDED BY 4.
# Waits follow _common.tape: destroy's two confirmations block (+Line on the
# prompt text), everything else anchors on the shell prompt returning.

Source "_common.tape"
Output "../assets/videos/cli-04-launch-destroy.mp4"

Set PlaybackSpeed 4
Set TypingSpeed 240ms

Source ".path.tape"

Hide
Type `export PS1="$ "` Enter
Type "clear" Enter
Show

# --- Step 5: Launch a client VM -------------------------------------------
Sleep 4s
Type "lablink client launch --num-vms 1" Sleep 2s Enter
Wait+Line /^\$$/
Sleep 12s

# The doc tells the reader to re-run status and watch the VM appear.
Type "clear" Sleep 1s Enter
Sleep 2s
Type "lablink status" Sleep 2s Enter
Wait+Line /^\$$/
Sleep 24s

# --- Step 6: Tear down ----------------------------------------------------
Type "clear" Sleep 1s Enter
Sleep 2s
Type "lablink destroy" Sleep 2s Enter

Wait+Line /Type 'yes' to confirm/
Sleep 8s
Type "yes" Sleep 2s Enter

# Declining the metrics export keeps the clip on the doc's happy path — the
# doc's Step 6 says nothing about a CSV, and answering Y would drop one in
# whatever directory the recording ran from.
Wait+Line /Export metrics before destroying/
Sleep 6s
Type "n" Sleep 1s Enter

Wait+Line /^\$$/
Sleep 16s

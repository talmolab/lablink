# docs/cli/first-deployment.md — Step 1: Configure
#
# A fresh `Config()` already defaults to this doc's happy path (us-west-2,
# g4dn.xlarge, software=sleap, IP-only DNS, no startup script, metrics off),
# so the deployment name is the ONLY value that has to be typed. Every other
# screen is "read it, accept it, move on".
#
# Navigation notes for anyone editing this:
#   * The wizard does NOT focus the first Input on mount — a bare `Type` is
#     swallowed. Always `Tab` into a field before typing.
#   * `Shift+Tab` on a freshly-pushed screen wraps focus backwards to the LAST
#     focusable widget, which is always the Next/Save button. That's the
#     uniform "advance" move and it survives fields being added to a screen.
#   * `q` is a global quit binding. Never send a stray `q` outside an Input.

Source "_common.tape"
Output "../assets/videos/cli-01-configure.mp4"

Hide
Type `export PS1="$ "` Enter
Type "clear" Enter
Show

Sleep 1s
Type "lablink configure" Sleep 500ms Enter

# --- Step 1: Deployment Identity -----------------------------------------
Wait+Screen /Deployment Name/
Sleep 2s
Tab
Type "sleap-workshop"
Sleep 1500ms
Tab Tab
Sleep 500ms
Enter

# --- Step 2: Provider (aws is already selected) ---------------------------
Wait+Screen /Step 2: Provider/
Sleep 3s
Shift+Tab
Sleep 500ms
Enter

# --- Step 2: AWS Region — the one real choice the doc calls out ------------
Wait+Screen /AWS Region/
Sleep 2s
Tab
Sleep 1s
Enter
Sleep 1500ms
Tab Tab
Sleep 500ms
Enter

# --- Step 3: Machine Configuration (g4dn.xlarge + sleap by default) --------
Wait+Screen /Machine Configuration/
Sleep 4s
Shift+Tab
Sleep 500ms
Enter

# --- Step 4: DNS & SSL (IP Only by default) -------------------------------
Wait+Screen /DNS & SSL/
Sleep 4s
Shift+Tab
Sleep 500ms
Enter

# --- Step 5: Client Startup Script (None by default) ----------------------
Wait+Screen /Startup Script/
Sleep 3s
Shift+Tab
Sleep 500ms
Enter

# --- Step 6: Session Metrics (Disabled by default) ------------------------
Wait+Screen /Session Metrics/
Sleep 3s
Shift+Tab
Sleep 500ms
Enter

# --- Step 7: Review & Save ------------------------------------------------
Wait+Screen /Review & Save/
Sleep 5s
Shift+Tab
Sleep 500ms
Enter

# --- configure then auto-runs `lablink setup` (S3 + DynamoDB) -------------
# `configure` auto-runs setup; wait for the shell to come back rather than
# for the summary table, which more output can scroll past.
Wait+Line /^\$$/
Sleep 5s

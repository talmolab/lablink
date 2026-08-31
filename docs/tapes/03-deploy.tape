# docs/cli/first-deployment.md — Steps 3-4: Deploy, then Verify
#
# *** THIS TAPE CREATES REAL AWS RESOURCES AND COSTS MONEY. ***
# Only run by `scripts/record-docs.sh --live|--all`; it leaves the allocator
# standing for 04-launch-destroy.tape to launch into and tear down.
#
# Timing: `tofu apply` plus the first-boot health wait is 3-8 minutes of
# spinner that is not content. `Set PlaybackSpeed 4` compresses the clip 4x
# at render time and TypingSpeed is multiplied to compensate, so typing still
# reads at the usual 60ms. Sleeps below are wall-clock:
# ON-SCREEN DURATION IS THE VALUE DIVIDED BY 4.
#
# Waits follow the rules in _common.tape. `tofu plan` scrolls hundreds of
# lines, so there is not a single Wait+Screen in this file: the credential
# and confirmation prompts block (so +Line on their text is safe), and
# everything else anchors on the shell prompt returning.
#
# The admin password is NOT in this file. record-docs.sh generates one per
# run into the gitignored .password.tape that the Hide block below sources.

Source "_common.tape"
Output "../assets/videos/cli-03-deploy.mp4"

Set PlaybackSpeed 4
Set TypingSpeed 240ms

Hide
Type `export PS1="$ "` Enter
Type "clear" Enter
Show

Sleep 4s
Type "lablink deploy" Sleep 2s Enter

# --- Admin credentials (doc Step 3, item 3) -------------------------------
# The username is the doc's documented default and is safe on camera.
Wait+Line /Admin username/
Sleep 4s
Type "admin" Sleep 1s Enter

# getpass already masks the password; Hide keeps the keystroke cadence off
# camera too, since cadence is a length hint.
Wait+Line /Admin password/
Sleep 2s
Hide
Source ".password.tape"
Show
Sleep 4s

# --- The plan confirmation the doc describes ------------------------------
# Arrives after the full `tofu plan` dump. It blocks on input(), so the
# prompt stays the current line and +Line matches reliably.
Wait+Line /Type 'yes' to apply/
Sleep 8s
Type "yes" Sleep 2s Enter

# --- Apply + health poll. Duration varies, so anchor on the prompt. -------
Wait+Line /^\$$/
Sleep 16s

# --- Step 4: Verify -------------------------------------------------------
Type "clear" Sleep 1s Enter
Sleep 2s
Type "lablink status" Sleep 2s Enter
Wait+Line /^\$$/
Sleep 24s

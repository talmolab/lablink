# docs/cli/byo-clients.md — Step 1: Configure (manual provider)
#
# Runs on the ALLOCATOR HOST. Purely local: no AWS, no docker, nothing
# created. Safe to re-run as often as you like — except that saving
# overwrites ~/.lablink/config.yaml, which record-docs.sh stashes first.
#
# The manual path is seven screens, same count as the AWS path but a
# different set:
#   1 Deployment Identity  2 Provider  3 Client image
#   4 Client connectivity  5 Startup Script  6 Session Metrics  7 Review
# DnsScreen is skipped entirely — that IS the doc's "picking the manual
# provider pins ssl.provider: none and skips the DNS/SSL screen" claim, so
# the clip is the evidence for it. The wizard also does NOT run `lablink
# setup` afterwards (no remote state to bootstrap), which is why this tape
# ends the moment the shell prompt returns.
#
# Navigation rules (verified against Textual 8.2.3 by replaying this exact
# key sequence through Pilot — see the AWS 01-configure.tape header for the
# two that both paths share):
#
#   * Every screen's focus chain STARTS on the VerticalScroll, not on the
#     first Input. A bare `Type` is swallowed; always `Tab` in first.
#   * `Shift+Tab` from that initial state wraps backwards to the LAST
#     focusable, which is always Next/Save. That's the "advance" move for
#     any screen this tape accepts the defaults on.
#   * Inside a RadioSet, `Down` only moves the HIGHLIGHT — it does not
#     select. `Space` is what presses the highlighted button. And once
#     focus is inside the RadioSet, Shift+Tab no longer lands on Next, so
#     the two screens that need a selection tab FORWARD past Back instead.

Source "_common.tape"
Output "../assets/videos/byo-01-configure.mp4"

Hide
Type `export PS1="$ "` Enter
Type "clear" Enter
Show

Sleep 1s
Type "lablink configure" Sleep 500ms Enter

# --- Screen 1: Deployment Identity ---------------------------------------
Wait+Screen /Deployment Name/
Sleep 2s
Tab
Type "smith-lab"
Sleep 1500ms
Tab Tab
Sleep 500ms
Enter

# --- Screen 2: Provider — the one screen the BYO path diverges on ---------
# Default is aws. Tab into the RadioSet, Down to highlight "manual", Space
# to actually press it, then forward past Back to Next.
Wait+Screen /Step 2: Provider/
Sleep 3s
Tab
Sleep 1s
Down
Sleep 1500ms
Space
Sleep 2s
Tab Tab
Sleep 500ms
Enter

# --- Screen 3: Client image (default is the published latest) -------------
Wait+Screen /Step 3: Client image/
Sleep 4s
Shift+Tab
Sleep 500ms
Enter

# --- Screen 4: Client connectivity + participant exposure -----------------
# This screen carries BOTH axes, and the clip sets both:
#
#   connectivity: reverse_tunnel   — where the CLIENTS are. They can't
#       accept inbound, so each dials out and holds a tunnel open.
#   participant_exposure: cloudflare_tunnel — where the PARTICIPANTS are.
#       Off-LAN, so the allocator is published at a hostname we own.
#
# That pairing is the real-world one: sessions proxy through the
# allocator's own nginx, so publishing the allocator publishes the desktops
# with it. (lan_direct is the one mode the validator refuses to combine
# with any exposure, precisely because it bypasses the allocator.)
#
# Two RadioSets, and the tab order CHANGES between them: the
# public-hostname Input is `disabled` — and therefore absent from Textual's
# focus chain — until cloudflare_tunnel is selected, at which point it
# appears between the exposure RadioSet and the Back button. Verified by
# replaying this sequence through Pilot; the chain really does grow by one.
Wait+Screen /Client connectivity/
Sleep 5s

# Connectivity: third button, so Down twice (Down only moves the highlight)
# then Space to press.
Tab
Sleep 1s
Down
Sleep 1s
Down
Sleep 1500ms
Space
Sleep 3s

# Participant exposure: none -> tailscale_funnel -> cloudflare_tunnel.
Tab
Sleep 1s
Down
Sleep 1s
Down
Sleep 1500ms
Space
Sleep 2s

# The hostname Input only now exists in the tab order.
Tab
Sleep 500ms
Type "lablink-testing.com"
Sleep 2500ms

Tab Tab
Sleep 500ms
Enter

# --- Screen 5: Client Startup Script (None by default) --------------------
Wait+Screen /Startup Script/
Sleep 3s
Shift+Tab
Sleep 500ms
Enter

# --- Screen 6: Session Metrics (Disabled by default) ----------------------
Wait+Screen /Session Metrics/
Sleep 3s
Shift+Tab
Sleep 500ms
Enter

# --- Screen 7: Review & Save ----------------------------------------------
# The review pane is a ~14-line window over the config, so only the head
# (through `dns:`) is visible on arrival. The values this clip is evidence
# for are spread across all of it: provider: manual near the top,
# ssl.provider: none in the middle, and the whole `manual:` block —
# connectivity, participant_exposure, public_hostname — at the very end.
# Page through so each is actually on camera instead of merely claimed by
# the caption.
#
# The TextArea is read_only=True, so these navigation keys move the cursor
# and cannot edit the YAML being shown. Focus starts on the VerticalScroll,
# so one Tab reaches it — and from inside it, Shift+Tab no longer wraps to
# Save, hence the forward Tab Tab past Back at the end.
Wait+Screen /Review & Save/
Sleep 4s
Tab
Sleep 500ms

# Second page: `ssl: provider: none` — the value the manual provider pins.
PageDown
Sleep 4s

# Tail: the `manual:` block — connectivity: reverse_tunnel,
# participant_exposure: cloudflare_tunnel, public_hostname.
PageDown
Sleep 1s
PageDown
Sleep 5s

Tab Tab
Sleep 500ms
Enter

# No `lablink setup` on this path: the prompt comes straight back.
Wait+Line /^\$$/
Sleep 4s

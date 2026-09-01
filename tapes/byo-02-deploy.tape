# docs/cli/byo-clients.md — Steps 2-3: Sanity check, then Deploy
#
# Runs on the ALLOCATOR HOST. Starts a real docker-compose stack (allocator
# + Postgres) that byo-04-status-destroy.tape tears down. Nothing here costs
# money and nothing leaves the machine — this is the whole point of the BYO
# path, and it's why these clips are re-recordable by anyone with docker,
# unlike the AWS set.
#
# `lablink deploy` under provider: manual prompts FOUR times, in this order
# (deploy_compose.py line numbers, because the order is not the intuitive one):
#
#   425  Cloudflare tunnel token   — the exposure preflight, FIRST
#   492  Admin username            } resolve_admin_credentials
#   492  Admin password            }
#   548  Proceed?                  — fires on EVERY non---yes deploy, not just
#                                    --render-only, even though the
#                                    render-only warning shares its block
#
# Answering these out of order, or missing one, parks the tape at the prompt
# for the full 20m WaitTimeout. Both of those were found the hard way.
#
# NEITHER credential is in this file. record-docs.sh writes both into
# gitignored fragments the Hide blocks below source: .password.tape (a fresh
# random password per run) and .cftoken.tape (from
# $LABLINK_CLOUDFLARE_TUNNEL_TOKEN in the recording shell).
#
# The token stays off camera in three independent ways: getpass masks it,
# Hide keeps even the keystroke cadence out of frame, and `start.sh` unsets
# it before launching cloudflared — which logs its whole environment at INFO.
# `_redact_secrets` is the fourth layer, for the failure path that dumps
# container logs.
#
# The REGISTER TOKEN *is* visible in the summary at the end, deliberately —
# it's the thing the next clip pastes, so hiding it would gut the clip. It's
# safe on camera: it belongs to a throwaway local stack that clip 04
# destroys, and the allocator mints a fresh one on every deploy.
#
# Timing: `docker compose up -d` plus the health poll runs ~30-90s once the
# allocator image is local. `Set PlaybackSpeed 2` halves that at render time
# with TypingSpeed doubled to compensate, so typing still reads at 60ms.
# SLEEPS BELOW ARE WALL-CLOCK: on-screen duration is the value halved.
#
# record-docs.sh pulls the allocator image before this tape starts. A cold
# `docker compose up` would otherwise spend minutes on a progress bar that
# is not content — the caption under this clip in the doc says so.

Source "_common.tape"
Output "../assets/videos/byo-02-deploy.mp4"

Set PlaybackSpeed 2
Set TypingSpeed 120ms

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

# --- Step 2: Sanity check -------------------------------------------------
# Under provider: manual, doctor checks docker and the compose plugin
# instead of OpenTofu/AWS.
Sleep 2s
Type "lablink doctor" Sleep 1s Enter
Wait+Line /^\$$/
Sleep 10s

# --- Step 3: Deploy the allocator ----------------------------------------
Type "clear" Sleep 1s Enter
Sleep 2s
Type "lablink deploy" Sleep 1s Enter

# --- Cloudflare tunnel token (deploy_compose.py:425) ----------------------
# Comes BEFORE the admin credentials. The hint above the prompt is several
# lines, so anchor on the prompt itself — the trailing colon keeps this from
# matching the hint's own use of the word "token".
Wait+Line /Cloudflare tunnel token:/
Sleep 4s
Hide
Source ".cftoken.tape"
Show
Sleep 2s

# The username is the doc's documented default and is safe on camera.
Wait+Line /Admin username/
Sleep 4s
Type "admin" Sleep 1s Enter

# getpass already masks the value; Hide keeps the keystroke cadence off
# camera too, since cadence is a length hint.
Wait+Line /Admin password/
Sleep 2s
Hide
Source ".password.tape"
Show
Sleep 2s

# --- The "Proceed?" confirmation -----------------------------------------
# Blocks on input(), so the prompt stays the current line and +Line matches
# reliably. `-y` would skip it, but the doc's Step 3 shows the plain command,
# so the clip shows what the reader will actually see.
Wait+Line /Proceed/
Sleep 6s
Type "y" Sleep 1s Enter

# Compose up + health poll. Duration varies, so anchor on the prompt
# returning rather than on any line the summary will scroll past.
Wait+Line /^\$$/

# Long dwell: the summary block is the payoff — the public https:// URL the
# tunnel now serves, admin user, register token, and the ready-to-paste
# `client register --tunnel` command that the next clip runs on the box.
#
# Note the deploy also polls the public hostname before printing this
# (_verify_public_hostname, up to 6 tries 5s apart) — that wait is inside
# the Wait+Line above, not here.
Sleep 30s

#!/usr/bin/env bash
# Record the terminal videos embedded in the CLI docs.
#
# AWS path — docs/cli/first-deployment.md:
#   ./scripts/record-docs.sh              # clips 01 + 02 (wizard, doctor)
#   ./scripts/record-docs.sh --all        # all four — CREATES REAL AWS RESOURCES
#
# BYO path — docs/cli/byo-clients.md (docker only, no AWS, no cost):
#   ./scripts/record-docs.sh --byo             # allocator host: 01, 02
#   ./scripts/record-docs.sh --box URL TOKEN   # the box: clip 03
#   ./scripts/record-docs.sh --byo-finish      # allocator host: 04, then destroy
#
# The BYO clips record the real-world pairing: manual.connectivity
# reverse_tunnel (clients dial out — no inbound address, no Tailscale) with
# manual.participant_exposure cloudflare_tunnel (the allocator published at
# a hostname you own, so participants need not be on its LAN). Clip 01's
# wizard selects both; every later clip inherits them from the config it
# wrote.
#
# --byo therefore needs a Cloudflare Tunnel token, from the environment so
# it is never typed on camera and never committed:
#
#   export LABLINK_CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoi...
#
# Get it from the tunnel's Docker install command in Cloudflare's Zero
# Trust dashboard (Networks > Tunnels). The tunnel must already route
# $RECORDING_HOSTNAME to http://localhost:80 on this machine.
#
# The BYO set spans two machines on purpose: byo-clients.md tells the reader
# to run `client register` on the machine being added, so recording it on the
# allocator host would contradict the instruction it illustrates. Hence three
# invocations: --byo leaves the allocator running and exits, --box records on
# the second machine, --byo-finish comes back and tears down.
#
# AWS clips 03/04 only run under --all, because they deploy the provider:aws
# config that clip 01's wizard writes. Recording them against whatever config
# was already lying around is how you deploy a BYO config by accident, so
# there is deliberately no mode that does that.
#
# Every clip records the WORKING TREE's CLI (the workspace venv's editable
# install), not the released one — so a recording can never silently lag
# behind main. Run `uv sync --all-packages --extra dev` from the repo root
# first, on both machines: --box needs the repo checked out anyway, since
# that is where the tapes live.
#
# AWS credentials are inherited from this shell: run `aws sso login` first.
# They are never typed inside a tape, so they never appear on camera.
set -euo pipefail

cd "$(dirname "$0")/.."
command -v vhs >/dev/null || { echo "vhs not installed: brew install vhs" >&2; exit 1; }

# Record against the working tree, not whatever `lablink` happens to be on
# PATH. The workspace venv installs the CLI editable, so prepending its bin
# is equivalent to `uv run lablink …` — without putting `uv run` on camera,
# where it would contradict the bare `lablink …` the docs tell readers to
# type. vhs inherits this shell's environment (the same mechanism the AWS
# tapes use for credentials), so no tape needs to know about it.
VENV_BIN="$PWD/.venv/bin"
[ -x "$VENV_BIN/lablink" ] || {
  echo "No $VENV_BIN/lablink." >&2
  echo "Run: uv sync --all-packages --extra dev   (from the repo root)" >&2
  exit 1; }
export PATH="$VENV_BIN:$PATH"

# The tapes run `Set Shell "bash"`, so the recorded shell sources ~/.bashrc
# and a dotfile that PREPENDS to PATH would shadow the venv — silently
# recording a different CLI than intended. Resolve it the same way vhs will
# rather than trusting the export above; this box may not be the one whose
# dotfiles were checked.
RESOLVED="$(bash -ic 'command -v lablink' 2>/dev/null | tail -1)"
[ "$RESOLVED" = "$VENV_BIN/lablink" ] || {
  echo "ERROR: an interactive bash resolves lablink to:" >&2
  echo "  ${RESOLVED:-(nothing)}" >&2
  echo "  expected $VENV_BIN/lablink" >&2
  echo "A shell startup file is prepending to PATH; fix it before recording." >&2
  exit 1; }
echo "Recording against: $RESOLVED ($(lablink --version 2>/dev/null | head -1))"

CONFIG="$HOME/.lablink/config.yaml"
BACKUP="$HOME/.lablink/config.yaml.record-backup"
PASSWORD_TAPE="docs/tapes/.password.tape"
REGISTER_TAPE="docs/tapes/.byo-register.tape"
CFTOKEN_TAPE="docs/tapes/.cftoken.tape"

# The hostname clip 01's wizard types. Keep the two in step: `lablink
# deploy` polls this name after the stack is up (_verify_public_hostname)
# and the register command handed to the box is built from it.
RECORDING_HOSTNAME="${LABLINK_RECORDING_HOSTNAME:-lablink-testing.com}"

# Published defaults. Override either if the deployment pins a different
# image — these are only used for the off-camera pre-pull, never rendered.
#
# Both are published amd64-only, so an arm64 host needs --platform or the
# pull fails outright with "no matching manifest for linux/arm64/v8" and the
# multi-GB download lands on camera instead. The runtime already pins the
# same platform in both places (templates/docker-compose.yml for the
# allocator, register.py's docker run for the client); this only makes the
# pre-pull agree with them.
ALLOCATOR_IMAGE="${LABLINK_ALLOCATOR_IMAGE:-ghcr.io/talmolab/lablink-allocator-image:linux-amd64-latest}"
CLIENT_IMAGE="${LABLINK_CLIENT_IMAGE:-ghcr.io/talmolab/lablink-client-base-image:latest}"

cleanup() {
  rm -f "$PASSWORD_TAPE" "$REGISTER_TAPE" "$CFTOKEN_TAPE"
  [ -f "$BACKUP" ] && mv -f "$BACKUP" "$CONFIG"
  return 0
}
trap cleanup EXIT INT TERM

record() {
  echo "==> $1"
  ( cd docs/tapes && vhs "$1" )
}

require_docker() {
  docker info >/dev/null 2>&1 || {
    echo "Docker is not running. Start it and re-run." >&2; exit 1; }
}

require_aws() {
  # Every AWS tape needs a session, not just the live ones: clip 01's wizard
  # auto-runs `lablink setup` to create the S3 state bucket and lock table.
  # Without credentials that step fails and the tape blocks on a prompt that
  # never comes, until WaitTimeout expires.
  aws sts get-caller-identity >/dev/null 2>&1 || {
    echo "No valid AWS session. Run 'aws sso login' first." >&2; exit 1; }
}

# Clip 01 (either path) records the wizard, which pre-fills from an existing
# config and would otherwise show the edit-a-deployment flow rather than the
# first-run flow the doc describes. Stashing also keeps a real config from
# being deployed by the later clips. Put it back however we exit.
stash_config() {
  [ -f "$CONFIG" ] && mv "$CONFIG" "$BACKUP"
  return 0
}

# `lablink deploy` always prompts for an admin password (--yes explicitly does
# not bypass it), and a committed tape must not carry a credential. Generate
# one per run and hand it to the deploy tape through this gitignored fragment,
# which the trap above deletes.
# openssl, not `tr </dev/urandom | head -c`: head closes the pipe early, tr
# dies of SIGPIPE, and pipefail turns that into a silent set -e exit.
make_password() {
  REC_PASSWORD="$(openssl rand -hex 10)"
  printf 'Type "%s"\nEnter\n' "$REC_PASSWORD" > "$PASSWORD_TAPE"
  echo "Admin login for this recording:  admin / $REC_PASSWORD"
  echo "(The last clip destroys the deployment, so this password dies with it.)"
}

# The wizard clip is what every later clip depends on. If it did not save
# (tape drift against a changed screen, a validation error), `lablink deploy`
# exits with "Config not found" and the next tape blocks on a prompt that
# never comes until WaitTimeout expires. Fail loudly instead.
assert_config_saved() {
  [ -f "$CONFIG" ] || {
    echo "ERROR: the wizard tape did not save $CONFIG." >&2
    echo "Check the clip before recording anything that deploys." >&2
    exit 1; }
  if [ -n "${1:-}" ]; then
    grep -q "^provider: $1\$" "$CONFIG" || {
      echo "ERROR: expected 'provider: $1' in $CONFIG after the wizard." >&2
      echo "The wizard tape's navigation has drifted — check the clip." >&2
      exit 1; }
  fi
}

# Same regex the CLI's own _extract_register_token uses. 2>&1 matters: the
# allocator logs to stderr, so without it grep sees nothing.
read_register_token() {
  docker logs lablink-allocator 2>&1 \
    | grep -oE 'REGISTER_TOKEN[[:space:]]*=[[:space:]]*"?[A-Za-z0-9_-]{20,}' \
    | tail -1 | grep -oE '[A-Za-z0-9_-]{20,}$' || true
}

case "${1:-}" in
  "")           MODE=aws ;;
  --all)        MODE=aws-all ;;
  --byo)        MODE=byo ;;
  --byo-finish) MODE=byo-finish ;;
  --box)        MODE=box ;;
  *) echo "usage: $0 [--all | --byo | --byo-finish | --box URL TOKEN]" >&2
     exit 1 ;;
esac

case "$MODE" in

aws|aws-all)
  require_aws
  stash_config
  if [ "$MODE" = aws-all ]; then
    echo "WARNING: recording against real AWS — this provisions EC2 and costs money."
    make_password
    # 03 leaves a deployment standing that 04 launches into and then destroys,
    # so they only make sense back to back and in this order.
    TAPES=(01-configure.tape 02-doctor.tape 03-deploy.tape 04-launch-destroy.tape)
  else
    TAPES=(01-configure.tape 02-doctor.tape)
  fi
  for tape in "${TAPES[@]}"; do
    record "$tape"
    [ "$tape" = "01-configure.tape" ] && assert_config_saved aws
  done
  ;;

byo)
  require_docker

  # Check before recording anything: a missing token does not fail fast, it
  # parks clip 02 at the hidden prompt until the 20m WaitTimeout — after
  # clip 01 has already overwritten the config. Same class of failure as
  # the unanswered "Proceed?", so it gets the same treatment.
  [ -n "${LABLINK_CLOUDFLARE_TUNNEL_TOKEN:-}" ] || {
    echo "LABLINK_CLOUDFLARE_TUNNEL_TOKEN is not set." >&2
    echo "Copy the token from the tunnel's Docker install command in" >&2
    echo "Cloudflare Zero Trust (Networks > Tunnels), then:" >&2
    echo "  export LABLINK_CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoi..." >&2
    exit 1; }

  stash_config
  make_password

  # Handed to clip 02's hidden prompt the same way the admin password is.
  # printf, not echo: a token beginning with a dash would be eaten as a flag.
  printf 'Type "%s"\nEnter\n' "$LABLINK_CLOUDFLARE_TUNNEL_TOKEN" > "$CFTOKEN_TAPE"

  record byo-01-configure.tape
  assert_config_saved manual

  # The mode matters as much as the provider: everything downstream assumes
  # reverse_tunnel. If the wizard tape's radio navigation drifts, the config
  # is silently lan_direct — and the failure surfaces two steps later, on the
  # OTHER machine, as a 400 rejecting clip 03's `--tunnel` registration.
  # Catch it here, next to the cause.
  for expected in "connectivity: reverse_tunnel" \
                  "participant_exposure: cloudflare_tunnel" \
                  "public_hostname: $RECORDING_HOSTNAME"; do
    grep -q "$expected" "$CONFIG" || {
      echo "ERROR: clip 01 did not set '$expected'. The manual block is:" >&2
      sed -n '/^manual:/,$p' "$CONFIG" >&2
      echo "That screen's navigation has drifted; check the clip." >&2
      exit 1; }
  done

  # A cold `docker compose up` spends minutes on a progress bar that is not
  # content. Non-fatal: compose pulls it itself if this fails, just slowly.
  echo "==> pre-pulling $ALLOCATOR_IMAGE (off camera)"
  docker pull --platform linux/amd64 "$ALLOCATOR_IMAGE" \
    || echo "  (pull failed — clip 02 will show the download)"

  record byo-02-deploy.tape

  # Clip 02 printed the register command inside the recording, not in this
  # terminal, so read it back out of the running allocator and hand the
  # operator the exact command to run on the box.
  TOKEN="$(read_register_token)"
  [ -n "$TOKEN" ] || {
    echo "ERROR: no REGISTER_TOKEN in the allocator's logs — did clip 02 deploy?" >&2
    exit 1; }
  echo
  echo "Allocator is up and LEFT RUNNING. Now record clip 03 ON THE BOX:"
  # https://<hostname>, not a LAN IP: the point of the exposure mode is that
  # the box need not be on this LAN at all, and the tunnel it dials out to
  # is derived from whatever --allocator-url it proved reachable.
  echo "  ./scripts/record-docs.sh --box https://$RECORDING_HOSTNAME $TOKEN"
  echo "then copy docs/assets/videos/byo-03-register.mp4 back here and run:"
  echo "  ./scripts/record-docs.sh --byo-finish"
  ;;

byo-finish)
  # Clip 04 is a separate invocation rather than the tail of --byo behind a
  # blocking `read`. A run that parks waiting for a human is one an agent
  # harness or CI timeout can orphan mid-deployment, leaving the stack up
  # and the trap unrun; two short invocations cannot be. It also means the
  # box can take as long as it needs.
  require_docker
  docker ps --filter "name=lablink-allocator" --format '{{.Names}}' \
    | grep -q . || {
      echo "No lablink-allocator container running — run '$0 --byo' first." >&2
      exit 1; }

  # Clip 04 opens on `lablink status`, which reads the deployment config.
  # --byo restored the operator's own config on exit, so put the recorded
  # deployment's saved copy back for the duration of this clip.
  DEPLOYED_CONFIG=""
  for c in "$HOME"/.lablink/compose/*/config.yaml; do
    [ -f "$c" ] || continue
    if [ -z "$DEPLOYED_CONFIG" ] || [ "$c" -nt "$DEPLOYED_CONFIG" ]; then
      DEPLOYED_CONFIG="$c"
    fi
  done
  [ -n "$DEPLOYED_CONFIG" ] || {
    echo "No rendered compose config found under ~/.lablink/compose/." >&2
    exit 1; }
  stash_config
  cp "$DEPLOYED_CONFIG" "$CONFIG"

  record byo-04-status-destroy.tape
  ;;

box)
  # Runs on the BOX. No config stash and no AWS: the box holds no deployment
  # config, only the ~/.lablink/client.env that `register` writes.
  URL="${2:-}"; TOKEN="${3:-}"
  [ -n "$URL" ] && [ -n "$TOKEN" ] || {
    echo "usage: $0 --box URL TOKEN" >&2; exit 1; }
  require_docker

  # --tunnel is unconditional: the allocator these clips record is deployed
  # with connectivity: reverse_tunnel, and the allocator rejects a
  # registration whose shape does not match its configured mode with a 400.
  #
  # The command line carries a per-run URL and token, so it cannot live in a
  # committed tape. Written here for the tape to Source — outside a Hide
  # block, because the typed command IS the content of the clip.
  printf 'Type "lablink client register --allocator-url %s --register-token %s --tunnel"\n' \
    "$URL" "$TOKEN" > "$REGISTER_TAPE"

  echo "==> pre-pulling $CLIENT_IMAGE (off camera)"
  docker pull --platform linux/amd64 "$CLIENT_IMAGE" \
    || echo "  (pull failed — the clip will show the download)"

  record byo-03-register.tape
  ;;
esac

echo "Done. Output in docs/assets/videos/"

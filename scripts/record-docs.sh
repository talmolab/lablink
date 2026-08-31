#!/usr/bin/env bash
# Record the terminal videos embedded in docs/cli/first-deployment.md.
#
#   ./scripts/record-docs.sh          # clips 01 + 02 (wizard, doctor)
#   ./scripts/record-docs.sh --live   # clips 03 + 04 — CREATES REAL AWS RESOURCES
#   ./scripts/record-docs.sh --all    # all four in order — RECOMMENDED
#
# --all is the mode that actually works end to end: clip 01's wizard writes
# the provider:aws config that clips 03/04 then deploy. Running --live on its
# own requires you to already have an AWS config in place.
#
# Credentials are inherited from this shell: run `aws sso login` first. They
# are never typed inside a tape, so they never appear on camera.
set -euo pipefail

cd "$(dirname "$0")/.."
command -v vhs >/dev/null || { echo "vhs not installed: brew install vhs" >&2; exit 1; }

CONFIG="$HOME/.lablink/config.yaml"
BACKUP="$HOME/.lablink/config.yaml.record-backup"
PASSWORD_TAPE="docs/tapes/.password.tape"

cleanup() {
  rm -f "$PASSWORD_TAPE"
  [ -f "$BACKUP" ] && mv -f "$BACKUP" "$CONFIG"
  return 0
}
trap cleanup EXIT INT TERM

# Every tape needs a session, not just the live ones: clip 01's wizard
# auto-runs `lablink setup` to create the S3 state bucket and lock table.
# Without credentials that step fails and the tape blocks on a prompt that
# never comes, until WaitTimeout expires 15 minutes later.
aws sts get-caller-identity >/dev/null 2>&1 || {
  echo "No valid AWS session. Run 'aws sso login' first." >&2; exit 1; }

MODE="${1:-}"

case "$MODE" in
  --live|--all) LIVE=1 ;;
  "")           LIVE=0 ;;
  *) echo "usage: $0 [--live|--all]" >&2; exit 1 ;;
esac

# Clip 01 records the wizard, which pre-fills from an existing config and
# would otherwise show the edit-a-deployment flow rather than the first-run
# flow the doc describes. Stashing also keeps a real BYO config from being
# deployed by clips 03/04. Put it back however we exit.
if [ "$MODE" != "--live" ] && [ -f "$CONFIG" ]; then
  mv "$CONFIG" "$BACKUP"
fi

if [ "$LIVE" = 1 ]; then
  echo "WARNING: recording against real AWS — this provisions EC2 and costs money."

  # --live on its own deploys whatever config is already in place, so it has
  # to be an AWS one. A provider:manual config sends `lablink deploy` down
  # the docker-compose path, which exits immediately and leaves the tape
  # blocking for the full 15m WaitTimeout on a prompt that never comes.
  if [ "$MODE" = "--live" ]; then
    [ -f "$CONFIG" ] || {
      echo "No $CONFIG — use --all to record the wizard first." >&2; exit 1; }
    if grep -qE '^provider:' "$CONFIG" \
       && ! grep -qE '^provider:[[:space:]]*aws[[:space:]]*$' "$CONFIG"; then
      echo "ERROR: $CONFIG is not a provider:aws config:" >&2
      grep -nE '^provider:' "$CONFIG" >&2
      echo "Clips 03/04 record the AWS path. Use --all to generate an AWS" >&2
      echo "config via the wizard (your current config is stashed and" >&2
      echo "restored), or point --live at an AWS config." >&2
      exit 1
    fi
  fi

  # `lablink deploy` always prompts for an admin password (--yes explicitly
  # does not bypass it), and a committed tape must not carry a credential.
  # Generate one per run and hand it to 03-deploy.tape through this
  # gitignored fragment, which the trap above deletes.
  # openssl, not `tr </dev/urandom | head -c`: head closes the pipe early,
  # tr dies of SIGPIPE, and pipefail turns that into a silent set -e exit.
  REC_PASSWORD="$(openssl rand -hex 10)"
  printf 'Type "%s"\nEnter\n' "$REC_PASSWORD" > "$PASSWORD_TAPE"
  echo "Admin login for this recording:  admin / $REC_PASSWORD"
  echo "(Clip 04 destroys the deployment, so this password dies with it.)"

  # 03 leaves a deployment standing that 04 launches into and then destroys,
  # so they only make sense back to back and in this order.
  if [ "$MODE" = "--all" ]; then
    TAPES=(01-configure.tape 02-doctor.tape 03-deploy.tape 04-launch-destroy.tape)
  else
    TAPES=(03-deploy.tape 04-launch-destroy.tape)
  fi
else
  TAPES=(01-configure.tape 02-doctor.tape)
fi

for tape in "${TAPES[@]}"; do
  echo "==> $tape"
  ( cd docs/tapes && vhs "$tape" )

  # Clips 02/03/04 all read the config that clip 01's wizard saves. If the
  # wizard did not save it (tape drift, a validation error), `lablink deploy`
  # exits with "Config not found" and the next tape blocks on a prompt that
  # never comes until WaitTimeout expires. Fail loudly instead.
  if [ "$tape" = "01-configure.tape" ] && [ ! -f "$CONFIG" ]; then
    echo "ERROR: 01-configure.tape did not save $CONFIG." >&2
    echo "Re-run without --all and check the clip before going live." >&2
    exit 1
  fi
done

echo "Done. Output in docs/assets/videos/"

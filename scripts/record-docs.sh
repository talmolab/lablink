#!/usr/bin/env bash
# Record the terminal videos embedded in docs/cli/first-deployment.md.
#
#   ./scripts/record-docs.sh         # clips 01 + 02 (wizard, doctor)
#   ./scripts/record-docs.sh --all   # all four — CREATES REAL AWS RESOURCES
#
# Clips 03/04 only run under --all, because they deploy the provider:aws
# config that clip 01's wizard writes. Recording them against whatever config
# was already lying around is how you deploy a BYO config by accident, so
# there is deliberately no mode that does that.
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

case "${1:-}" in
  "")    ALL=0 ;;
  --all) ALL=1 ;;
  *) echo "usage: $0 [--all]" >&2; exit 1 ;;
esac

# Every tape needs a session, not just the live ones: clip 01's wizard
# auto-runs `lablink setup` to create the S3 state bucket and lock table.
# Without credentials that step fails and the tape blocks on a prompt that
# never comes, until WaitTimeout expires.
aws sts get-caller-identity >/dev/null 2>&1 || {
  echo "No valid AWS session. Run 'aws sso login' first." >&2; exit 1; }

# Clip 01 records the wizard, which pre-fills from an existing config and
# would otherwise show the edit-a-deployment flow rather than the first-run
# flow the doc describes. Stashing also keeps a real BYO config from being
# deployed by clips 03/04. Put it back however we exit.
[ -f "$CONFIG" ] && mv "$CONFIG" "$BACKUP"

if [ "$ALL" = 1 ]; then
  echo "WARNING: recording against real AWS — this provisions EC2 and costs money."

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
  TAPES=(01-configure.tape 02-doctor.tape 03-deploy.tape 04-launch-destroy.tape)
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

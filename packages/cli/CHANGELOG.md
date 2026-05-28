# lablink-cli Changelog

All notable changes to **lablink-cli** will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and
this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `manual` provider for bring-your-own (BYO) GPU boxes. `lablink configure`
  now offers an AWS-vs-Manual provider screen; manual deployments run the
  allocator via `docker-compose` on the operator's host and skip the AWS
  Terraform/S3/DynamoDB setup entirely.
- `lablink client` subgroup (`launch`, `register`, `unregister`) — see
  **Changed → Breaking** below for the rename details.
- `lablink destroy --purge` (manual provider only) — also deletes the
  Postgres data volume and compose working directory.
- `self-signed` SSL provider option in the wizard for closed-LAN labs.

### Changed

- **Breaking:** the following top-level commands have moved under the new
  `client` subgroup. Existing scripts must be updated:

  | Old                          | New                                 |
  | ---------------------------- | ----------------------------------- |
  | `lablink launch-client`      | `lablink client launch`             |
  | `lablink register`           | `lablink client register`           |
  | (new)                        | `lablink client unregister`         |

  No deprecation alias is provided — the old names exit with
  `No such command`. The `--help` text, `docs/reference/cli.md`, and the
  admin BYO-onboarding page all reference the new names.

- `lablink register` (now `lablink client register`) passes
  `docker run --pull always` so a republished image tag actually lands on
  the BYO box, and publishes `7070:7070` + `6080:6080` explicitly instead
  of using `--network host` (which silently breaks on Docker Desktop).

- `lablink doctor` now branches on `cfg.provider`: manual configs check
  `docker` + `docker compose` instead of Terraform / AWS credentials. A
  malformed `~/.lablink/config.yaml` now prints a yellow warning before
  falling through to AWS prereqs, instead of silently treating a broken
  config as "no config."

- `lablink status` for manual deployments reports `docker compose ps`,
  the allocator `/api/health` endpoint, and registered BYO clients via
  the new `GET /api/v1/clients` endpoint.

### Fixed

- LAN-direct browser auth: switched from HTTP BasicAuth (browser-blocked
  on WebSocket upgrades) to RFB `VncAuth` with a per-session 8-byte
  credential. Includes a `sed` patch on the bundled KasmVNC noVNC to undo
  an upstream `this._rfbCredentials.password=""` clobber. AWS deployments
  are byte-identical and regression-locked by `test_desktop_aws_byte_identical`.

- Allocator `terraform init` and the auto-reboot service now gate on
  provider capability flags (`can_provision_hosts`, `can_recover_hosts`)
  instead of provider-type equality, so manual deployments without AWS
  credentials no longer spam `NoCredentialsError` every reboot interval.

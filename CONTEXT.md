# Domain glossary

Terms with a precise meaning in this codebase. Architecture reviews and new
code should use these names, not synonyms.

- **Manual deployment** — a LabLink stack the operator runs themselves with
  `provider: manual`: the allocator as a local compose stack, clients brought
  by the operator (BYO) via `lablink register`. Contrast: AWS deployment,
  where OpenTofu provisions everything.
- **Compose workdir** — `~/.lablink/compose/<deployment_name>/`, the rendered
  compose directory for one manual deployment: compose file, saved
  `config.yaml`, `.env`, canonical-URL file. Owned by `lablink_cli/manual.py`
  (`manual.workdir(cfg, root=None)`); nothing else derives this path.
- **Allocator base URL** — the address the CLI uses to reach the allocator's
  API. For manual deployments this is always `http://localhost:<HTTP_PORT>`
  (the compose stack publishes `${HTTP_PORT}:5000` and the manual CLI paths
  run on that host). Owned by `manual.base_url(cfg)`; the AWS ladder lives in
  `commands/utils.get_allocator_url`.
- **Canonical URL file** — `allocator-url`, staged in the compose workdir and
  bind-mounted into the allocator: the participant-facing public URL written
  at deploy time (e.g. from `tailscale funnel status`). Deliberately spelled
  in both packages (per-package CI installs forbid a cross-package import),
  guarded by a filename-sync test.
- **Participant exposure** — how participants reach a manual allocator:
  `none`, `tailscale_funnel`, or `cloudflare_tunnel` (`manual.participant_exposure`).
  Distinct from **connectivity** (`manual.connectivity`), which is how client
  VMs reach the allocator: `lan_direct`, `mesh_overlay`, `reverse_tunnel`.

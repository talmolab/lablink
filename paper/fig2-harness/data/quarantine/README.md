# Quarantined runs — pre-fix diagnostics, NOT figure inputs

## n030-r1-5778e5663b (N=30, replicate 1)

Quarantined 2026-09-02. This run was collected against an allocator whose
`assign_vm` treated a temporarily locked eligible row as an empty pool:
`FOR UPDATE SKIP LOCKED` skips rows other in-flight transactions hold, and
the code raised "no seats" without checking whether an eligible VM still
existed. Observed effect in this run: VM 9 ended running, Healthy, and
unassigned while seat request 12 received a 503 no_seats.

Fix (uncommitted at quarantine time): bounded retry in
`packages/allocator/src/lablink_allocator_service/db/vms.py::assign_vm` —
on an empty claim, an EXISTS check with the identical eligibility clause
decides between "genuinely empty" (ValueError -> 503) and "transiently
locked" (retry, 10 attempts, 10 ms -> 100 ms exponential backoff, ~0.65 s
worst case, then RuntimeError). Regression test:
`tests/db/test_vms.py::test_assign_vm_retries_temporarily_locked_eligible_vm`
(real Postgres; locks the only free row, releases mid-retry, asserts the
claim lands).

The run is preserved verbatim as the diagnostic that found the bug. Its
claims.csv 503 rate is a property of the pre-fix allocator, not of the
pool, so it must not enter panel D. Plot discovery
(`data_dir.glob("*/meta.json")`) does not descend into this directory.

N=5 and N=10 runs collected under the same pre-fix allocator remain in
data/ but are superseded: rerun 5/10/30 under the fixed allocator SHA for
comparability before plotting.

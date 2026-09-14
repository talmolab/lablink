N=60 rep1 (f29a57c79e): claim burst 60/60 is valid, but the polled trajectory
has two >20s coverage gaps — 173s during terraform apply (launch_started, before
any VM registers) and 298s during terraform destroy. Both fall outside the
readiness ramp and soak (which polled at the normal 5s), so readiness is sound,
but the run fails plot_fig2.py's blanket >20s eligibility guard and is excluded
from panels B/C/D. Its events.jsonl still feeds the Panel A timeline. Re-run with
continuous polling for a figure-eligible N=60 B/C/D point.

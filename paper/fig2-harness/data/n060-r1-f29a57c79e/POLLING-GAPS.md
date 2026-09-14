# N = 60 run: poller coverage gaps

N=60 rep1 (f29a57c79e): the claim burst is valid (60/60), but the polled
trajectory has two coverage gaps over 20 s: 173 s during `terraform apply`
(after `launch_started`, before any VM had registered) and 298 s during
`terraform destroy`. Both fall outside the readiness ramp and the soak, which
polled at the normal 5 s cadence, so the readiness and outcome data are sound.

The run failed the earlier plotter's (`plot_fig2.py`) blanket >20 s
eligibility guard and was filed under `data/ineligible/` at the time. The
current `replot_fig2.py` includes it: the gaps do not overlap the window it
measures (first VM registering through all 60 VMs ready).

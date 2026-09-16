---
title: "LabLink: On-demand GPU teaching labs accessible through the browser"
tags:
  - Python
  - Virtual Machine
  - infrastructure-as-code
  - Reproducibility
authors:
  - name: Andrew Park
    orcid: 0009-0000-7942-5666
    affiliation: 1
  - name: Elizabeth Berrigan
    orcid: 0000-0002-6217-4108
    affiliation: 1
  - name: Liezl Maree
    orcid: 0000-0002-9781-3627
    affiliation: 1
  - name: Talmo Pereira
    orcid: 0000-0001-9075-8365
    affiliation: 1
    corresponding: true

affiliations:
  - index: 1
    name: "Salk Institute for Biological Studies, La Jolla, California, United States"
date: 14 September 2026
bibliography: paper.bib
---

# Summary

Quantitative biology increasingly relies on GPU-accelerated deep learning
tools with graphical interfaces, but teaching them hands-on is hard:
installation consumes the opening hours of a workshop, and many
participants' laptops have no GPU. LabLink is an open-source
Infrastructure-as-Code platform with which a research group deploys
reproducible GPU desktops in its own Amazon Web Services (AWS) account or on
any machines that run Docker. Each participant claims a seat by entering an
email address and lands in a full Linux desktop with the instructor's
software preinstalled, in a browser tab (\autoref{fig:overview}). In our
benchmark, a 30-seat pool was ready about seven minutes after a cold start.
LabLink has served approximately 600 participants across 15 events.

![LabLink overview. (A) An operator deploys the allocator into their own
cloud account or onto a lab-owned server with one CLI command; it provisions
or registers one client machine per participant and monitors its health.
Participants enter an email address and receive a Linux desktop streamed to
their browser. (B) SLEAP v1.6.3 running in a LabLink browser
desktop.\label{fig:overview}](fig1.png)

# Statement of need

Hands-on workshops are how research software spreads [@wilson2016swc], but
GPU-dependent software is hard to teach. Installation means resolving
dependency stacks, GPU drivers, and operating-system-specific configuration
[@mangul2019installability], and the first hours of a workshop are routinely
lost to it. Many participants also have no local GPU, so even a successful
installation cannot run training or inference.

The common workarounds each sacrifice something: preinstallation shifts the
burden onto the least experienced users, shared teaching servers require
institutional infrastructure most labs lack, and cloud notebooks do not, by
default, run graphical desktop applications. LabLink closes this gap: a lab
creates a pool of identical, isolated, GPU-backed Linux desktops in its own
cloud account or on machines it already has, hands each participant one link,
and tears everything down when the workshop ends. It targets maintainers and
instructors of GPU-dependent scientific software who must equip a room
without per-laptop setup or institutional computing infrastructure.

# State of the field

Domain platforms such as brainlife.io [@hayashi2024brainlife], Neurodesk
[@renton2024neurodesk], brainchop [@masoud2023brainchop], and NeuroCAAS
[@abe2022neurocaas] serve their own catalogs of neuroimaging environments or
batch analyses, not software the instructor packages.

General-purpose teaching infrastructure is notebook-centric. JupyterHub
[@jupyterhub] can stream a Linux desktop through jupyter-remote-desktop-proxy
[@jupyterdesktopproxy], but as a standing service someone must keep running:
on one server with The Littlest JupyterHub [@tljh], on a Kubernetes cluster
for larger classes and for BinderHub [@jupyter2018binder], or hosted by a
provider such as 2i2c [@twoi2c]. LabLink starts one level down: from an image
of the instructor's software and the lab's cloud credentials, one command
provisions a GPU machine per participant and a second removes all of it, so
the lab operates nothing between events. Google Colab [@googlecolab] offers
GPUs only in notebooks, with session limits and no instructor control, and
Galaxy's Training Infrastructure as a Service [@rasche2023tiaas] serves
Galaxy workflows on shared public servers.

Among browser remote desktops, Apache Guacamole [@guacamole] gateways a
browser to existing machines, Open OnDemand [@hudak2018openondemand] serves
desktops from an institutional HPC cluster, Kasm Workspaces [@kasmworkspaces]
runs containerized desktops as an account-based service, Azure Lab Services
[@azurelabservices] provisioned per-student VM pools but retires in June
2027, and Amazon WorkSpaces [@awsworkspaces] streams managed GPU desktops
bound to AWS.

LabLink's contribution is the integration around the desktop rather than the
desktop itself: one GPU machine per participant, provisioned reproducibly in
infrastructure the operator owns, running instructor-packaged software, with
accountless email-based seat claiming, health monitoring with automatic
recovery, and teardown when the event ends.

# Software design

LabLink has two components. A single **allocator** per deployment holds the
cloud credentials that run OpenTofu [@opentofu], the database of machines and
seats, the participant-facing web page, and the nginx [@nginx] proxy through
which desktops are reached. A **client service** on every machine registers
it, reports heartbeats, GPU health, and seat status, ships its logs, and
rotates the desktop password when a seat is claimed. Because every report is
a client-initiated REST call, a machine needs no public address or inbound
rule, so machines LabLink did not provision, even behind an institutional
firewall, can join the same pool. Except for direct LAN access, desktops are
streamed over WebSockets through the allocator, the deployment's single
participant-facing endpoint.

The allocator is a Flask [@flask] service backed by PostgreSQL
[@postgresql], whose row-level locking lets a burst of simultaneous claims
each take a different free machine. OpenTofu provisions cloud machines in the
background; only a small state bucket and lock table persist between events.
On AWS the allocator sweeps the pool once a minute and reboots any machine
that fails to start, fails its GPU check, or goes silent, warm to preserve an
assigned session; after three failures its seat is released. Bring-your-own
hosts are monitored but not rebooted.

Each client machine runs one Docker [@merkel2014docker] container built from
the instructor's image, hosting both the KasmVNC [@kasmvnc] desktop and the
client service. A whole machine per participant trades cost for isolation:
one crashed session or saturated GPU affects only its own seat. At us-west-2
on-demand prices [@awsec2pricing], a `g4dn.xlarge` seat costs about \$0.53
per hour, roughly \$2 per participant for a four-hour workshop. KasmVNC
replaced Chrome Remote Desktop [@chromeremotedesktop], used at LabLink's
first events, which required a Google account per participant and could not
be version-pinned.

The allocator's own infrastructure is defined in a separate [template
repository](https://github.com/talmolab/lablink-template), deployed from a
laptop with `lablink-cli` or through the template's GitHub Actions workflows.
The `manual` provider registers, monitors, and proxies bring-your-own
machines but leaves their creation and teardown to the operator, so only the
AWS provider delivers the full provision-to-destroy lifecycle. Each package
is tested and published to PyPI independently, with 90% coverage enforced and
the allocator's OpenTofu tests run against AWS in CI; production images are
built only from published versions. Documentation is at
<https://lablink.talmolab.org/>.

## Security

TLS is a configuration option, not a default; a bare-IP deployment runs over
plain HTTP. Operator pages require operator credentials; client machines hold
only per-machine secrets minted at registration and, on AWS, accept inbound
connections only from the allocator and operator SSH; participants are
administrators inside their desktop container but not on the host. The
seat-claim page is deliberately unauthenticated: an email address labels a
seat rather than authenticating a user, acceptable only because a deployment
is short-lived with a fixed pool: a leaked link can exhaust seats but not
provision machines, one address holds one seat, and scheduled destruction
bounds the exposure. Claiming a seat rotates the desktop password and binds
the browser to a signed session cookie, so participants cannot open one
another's seats.

## Configuration and adaptability

One YAML file, read by both deployment paths and the allocator, is the
version-controllable record of a deployment, with no per-setting overrides.
It states where machines come from; how the allocator reaches each desktop
and participants reach the allocator (the AWS private network, a LAN, a
WireGuard mesh overlay, or a client-initiated tunnel, plus Tailscale Funnel
[@tailscalefunnel] or Cloudflare Tunnel [@cloudflaretunnel] for an allocator
without a public address); and a startup script that installs the
instructor's software at boot, with retries because parallel installs fail
intermittently at scale. Adapting to new software means editing these two
files.

## Benchmark

We deployed pools of 5, 10, 30, 60, and 150 `g4dn.xlarge` seats in
us-west-2, one run per pool size (\autoref{fig:benchmark}); script, metadata,
and raw data are in `paper/fig2-harness/`. Readiness is measured from the
pool-launch command until the allocator marks a VM assignable, excluding the
one-time allocator deploy.

From a cold start, a ready 30-seat pool takes about seven minutes. Per-client
median readiness stayed near five minutes from 5 to 60 seats and about six
and a half at 150, the size of our largest event, where all VMs were ready 11
minutes after launch; the infrastructure apply grew from 83 s to 249 s while
boot time grew only modestly. All 255 VMs reached ready; ten (two at 10
seats, eight at 150) needed one automatic reboot after failing at the same
point in the client-image pull, a transient registry failure rather than
faulty machines.

![Workshop-scale benchmark, 5 to 150 seats. (A) Wall-clock to prepare one
30-seat workshop: allocator deploy (126 s), client-VM apply (83 s), and boot
until all 30 VMs were ready (229 s). (B) Per-client readiness time (median
and interquartile range) by pool size N. (C) Client VM outcomes per pool:
ready directly, after one automatic reboot, or
failed.\label{fig:benchmark}](fig2.png)

# Research impact statement

LabLink was built to run SLEAP [@pereira2022sleap] workshops and has
delivered on-demand GPU desktops at 15 events between 2024 and 2026
(\autoref{tbl:events}), from K–12 students to faculty, totaling approximately
600 attendances with nothing installed on participants' machines; the 2024
events ran on an earlier Chrome Remote Desktop-based implementation that
predates the current repository.

LabLink's contribution to research is dissemination: installation is a
documented barrier to adoption [@mangul2019installability], and a hands-on
workshop is often a researcher's first chance to try GPU-dependent software.
The approach generalizes beyond SLEAP: environments for Cellpose
[@stringer2021cellpose], Kilosort4 [@pachitariu2024kilosort4], idtracker.ai
[@romeroferrero2019idtracker], and DeepLabCut [@mathis2018deeplabcut] each
required changing only the configuration and startup script.

--------------------------------------------------------------------------------------------------------------------------------------------
Event                                                     Date(s)                     Participants            Location
--------------------------------------------------------  --------------------------  ----------------------  ------------------------------
Cosyne Main Tutorial – SLEAP                              Feb 29, 2024                ~150                    Lisbon, Portugal

University of Illinois Urbana–Champaign workshop          Apr 2, 2024                 ~40                     Urbana, IL, USA

Keiller Leadership Academy STEM Day                       May 30, 2024                ~125 (K–12 students)    San Diego, CA, USA

CAJAL Advanced Neuroscience Training Programme            Jun 2024                    ~20                     Lisbon, Portugal

Salk EDGE Summer Program                                  Jul 24, 2024                3                       La Jolla, CA, USA

NYU Langone Neuroscience T32 Workshop                     Aug 19, 2024                ~25                     New York, NY, USA

Ellen Potter Research Connections                         Apr 9–10, 2025              ~20                     La Jolla, CA, USA

Bridges to the Future Symposium                           May 28, 2025                ~50                     La Jolla, CA, USA

CAJAL Advanced Neuroscience Training Programme            Jun 8–27, 2025              ~30                     Lisbon, Portugal

Zagreb NeuroData Summer School                            Jul 2025                    ~30                     Online / Zagreb, Croatia

Salk EDGE Summer Program                                  Jul 14–15, 2025             2                       La Jolla, CA, USA

Computer Vision for Biologists                            Sep 1–12, 2025              ~30                     Davis, CA, USA

Introduction to Multi-Animal Pose Tracking (US-RSE 2025)  Oct 6, 2025                 ~30                     Philadelphia, PA, USA

Short course on machine learning applications             Oct 13–17, 2025             ~30                     Bar Harbor, ME, USA

CAJAL Advanced Neuroscience Training Programme            Jun 10, 2026                18                      Lisbon, Portugal
--------------------------------------------------------------------------------------------------------------------------------------------

Table: Workshops and courses delivered on LabLink, 2024–2026. Participant counts marked ~ are organizer estimates.\label{tbl:events}

# AI usage disclosure

Claude Opus 5 and Claude Fable 5.1 (Anthropic), through Claude Code, assisted
with both the software and this manuscript. The authors designed and wrote
the architecture and initial implementation; Claude Code later drafted code
and documentation, which the authors reviewed and validated with the test
suites and in live deployments. The authors drafted the paper; Claude
reviewed and shortened the text, checked citations, and helped assemble the
benchmark figure. All text and figures were reviewed by the authors.

# Acknowledgements

This work was supported by the NIH/BRAIN Initiative RF1 award under grant
number 1RF1MH132653-01. We thank the open-source projects that made this work
possible, including OpenTofu, Docker, KasmVNC, and PostgreSQL.

# References

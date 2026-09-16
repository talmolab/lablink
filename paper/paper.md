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
any machines that run Docker. Its allocator manages and monitors participant
machines, whether provisioned on AWS or registered by the operator. Each
participant claims a seat by entering an email address on a web page and
lands in a full Linux desktop with the instructor's software preinstalled,
running in a browser tab (\autoref{fig:overview}). In our benchmark, a
30-seat pool was ready about seven minutes after a cold start. LabLink has
served approximately 600 participants across 15 events, from K–12 students
to faculty.

![LabLink overview. (A) An operator deploys the allocator into their own
cloud account or onto a lab-owned server with a single CLI command; the
allocator manages one client VM per participant (provisioned on AWS, or
registered bring-your-own machines) and monitors their health. Participants
enter an email address and receive a full Linux desktop
streamed to their browser. (B) The participant's view: SLEAP v1.6.3 running in a LabLink
browser desktop.\label{fig:overview}](fig1.png)

# Statement of need

Hands-on workshops are how research software spreads [@wilson2016swc], but
GPU-dependent scientific software is hard to teach. Installation means
resolving dependency stacks, GPU drivers, and operating-system-specific
configuration [@mangul2019installability], and the first hours of a workshop
are routinely lost to it. Many participants also have no local GPU, so even a
successful installation cannot run training or inference.

The common workarounds each sacrifice something: asking participants to
preinstall shifts the burden onto the least experienced users, shared
teaching servers require institutional infrastructure most labs lack, and
cloud notebooks solve hardware access but do not, by default, run desktop
applications with graphical interfaces. LabLink closes this gap: a lab
creates a pool of identical, isolated, GPU-backed Linux desktops in its own
cloud account or on machines it already has, hands each participant one link,
and tears everything down when the workshop ends. It targets maintainers and
instructors of GPU-dependent scientific software who must equip a room of
participants without per-laptop setup or institutional computing
infrastructure.

# State of the field

Domain platforms such as brainlife.io [@hayashi2024brainlife], Neurodesk
[@renton2024neurodesk], and brainchop [@masoud2023brainchop] deliver
cloud-based or in-browser neuroimaging environments, and NeuroCAAS
[@abe2022neurocaas] applies infrastructure-as-code to neuroscience analyses
run as batch jobs. Each serves its own application catalog, not software
the instructor packages.

General-purpose teaching infrastructure is notebook-centric. JupyterHub
[@jupyterhub] can stream a Linux desktop through jupyter-remote-desktop-proxy
[@jupyterdesktopproxy], but as a standing service someone must keep running:
on one server with The Littlest JupyterHub [@tljh], on a Kubernetes cluster
for larger classes and for BinderHub [@jupyter2018binder], or hosted by a provider
such as 2i2c [@twoi2c]. LabLink starts one level down: from an
image of the instructor's software and the lab's cloud credentials, one
command provisions a GPU machine per participant and a second removes all of
it, so the lab operates nothing between events. Browser development
environments such as GitHub Codespaces [@githubcodespaces], Gitpod [@gitpod],
and Coder [@coder] offer editors and terminals rather than GPU desktops, and
Google Colab [@googlecolab] offers GPUs only in notebooks, with session limits
and no instructor control. The Galaxy project's Training
Infrastructure as a Service [@rasche2023tiaas] serves Galaxy workflows on
shared public servers, not an instructor's own software.

Browser remote desktops are well established: Apache
Guacamole [@guacamole] gateways a browser to existing machines, Open OnDemand
[@hudak2018openondemand] delivers desktops from an institutional HPC cluster,
and Kasm Workspaces [@kasmworkspaces] orchestrates containerized desktops as
an account-based service an administrator maintains. Cloud vendors do the
same: Azure Lab Services [@azurelabservices] provisioned per-student VM pools
but retires in June 2027, and Amazon WorkSpaces [@awsworkspaces] streams
managed GPU desktops bound to AWS.

LabLink's contribution is the integration around the desktop rather than the
desktop itself: one GPU machine per participant, provisioned reproducibly in
infrastructure the operator owns, running instructor-packaged software, with
accountless email-based seat claiming, health monitoring with automatic
recovery, and teardown when the event ends. We wrote new software because the
missing piece is the workshop lifecycle: existing platforms are standing
services an administrator maintains, whereas a LabLink deployment is created
for one event and destroyed afterward.

# Software design

LabLink has two components, split by where the work has to happen. A single
**allocator** per deployment holds the cloud credentials that run OpenTofu,
the database of machines and seats, the participant-facing web page, and the
proxy through which desktops are reached. A **client service** runs on every
machine and does the work that must happen on that machine: it registers the
machine, reports heartbeats, GPU health, and seat status, ships its logs, and
rotates the desktop password when a seat is claimed. Because every report is a client-initiated REST call, a machine
needs no public address and no inbound rule from the internet, which lets
machines LabLink did not provision, even behind an institutional firewall,
join the same pool. On AWS, and in every bring-your-own topology except
direct LAN access, the participant's desktop is streamed over WebSockets and
proxied through the allocator's nginx [@nginx], so the allocator is the
deployment's single participant-facing endpoint.

The allocator is a Flask [@flask] service backed by PostgreSQL
[@postgresql], chosen over an embedded database because row-level locking
lets a burst of simultaneous claims each take a different free machine.
Cloud machines are provisioned by OpenTofu [@opentofu] runs in the
background; declarative infrastructure makes teardown of a per-event
deployment's compute repeatable, and only a small state bucket and lock table
persist between events. It also serves the admin dashboard and can destroy
the pool at a scheduled time. On AWS it sweeps the pool once a minute and reboots any machine that reports a
startup failure, fails its GPU check, stalls while initializing, or goes
silent: cold if unassigned, and warm, preserving the session, if assigned;
after three failures its seat is released.
Bring-your-own hosts are monitored but not rebooted.

Each client machine runs one Docker [@merkel2014docker] container built from
the instructor's image, hosting both the KasmVNC [@kasmvnc] desktop and the
client service. Giving each participant a whole machine rather than a slice
of a shared server trades cost for isolation: one
participant's crashed session or saturated GPU affects only their own seat.
At us-west-2 on-demand prices [@awsec2pricing], a `g4dn.xlarge` seat costs
about \$0.53 per hour, roughly \$2 per participant for a four-hour workshop.

KasmVNC replaced Chrome Remote Desktop [@chromeremotedesktop], used for
LabLink's first events, which required every participant to hold a Google
account and, in our experience, could not be version-pinned: two successive
releases of its apt package broke the client image, and superseded versions
left Google's repository within weeks. KasmVNC is open source, needs only a
browser, and is pinned to an exact version in the client image.

The allocator's own infrastructure is defined in a separate [template
repository](https://github.com/talmolab/lablink-template), deployed either
from a laptop with `lablink-cli` or, for reviewed infrastructure changes, by
forking the template and using its GitHub Actions workflows; both deploy the
same allocator image. The `manual` provider is how bring-your-own machines
join: the allocator registers, monitors, and proxies them but leaves their
creation and teardown to the operator, so only the AWS provider delivers the
full provision-to-destroy lifecycle.

## Development and release

Each package is tested and published to PyPI independently
(`lablink-allocator-service`, `lablink-client-service`, `lablink-cli`), with
90% coverage enforced on the allocator and client and the allocator's
OpenTofu tests run against AWS in CI. The image a workshop pins is built
from the same artifact anyone can install.
Working-tree builds are tagged `-test` with their commit hash and tested
inside the image; production images are built only from published PyPI
versions, so any production image can be rebuilt from its version number.
Documentation is at <https://lablink.talmolab.org/>.

## Security

TLS is a configuration option, not a default; a bare-IP deployment runs over
plain HTTP. Operator pages require operator credentials;
client machines hold only per-machine secrets minted at registration. On AWS
a client machine accepts inbound connections only from the allocator and from
operator SSH, and participants are administrators inside their desktop
container but not on the host.

The seat-claim page is deliberately unauthenticated: an email address labels
a seat rather than authenticating a user, and nothing gates it. This is
acceptable only because a deployment is short-lived with a fixed pool: a
leaked link can exhaust seats but cannot provision machines, one address
holds one seat, and scheduled destruction bounds the exposure. Claiming a
seat rotates the desktop password and binds the browser to a signed session
cookie, so participants cannot open one another's seats. The address is never
verified and dies with the deployment.

## Configuration and adaptability

One YAML file describes a deployment and is read by both deployment paths and
the allocator; apart from the startup script there are
deliberately no per-setting overrides, so the file is the
version-controllable record of a deployment. It answers three questions: (1)
where machines come from; (2) how the allocator reaches each desktop and
participants reach the allocator (on AWS, the private network; for
bring-your-own machines, the LAN, a WireGuard mesh overlay, or a
client-initiated WebSocket tunnel, plus a Tailscale Funnel [@tailscalefunnel]
or Cloudflare Tunnel [@cloudflaretunnel] when the allocator has no public
address); and (3) what runs on each desktop. The last is a startup script that
installs the instructor's software as the container boots, with retries and
an optional success check, since parallel installs fail intermittently at
scale. Thus, adapting to new software means editing these two files.

## Benchmark

We deployed pools of 5, 10, 30, 60, and 150 `g4dn.xlarge` seats in
us-west-2, one run per pool size (\autoref{fig:benchmark}). Per-VM readiness
runs from the pool-launch command until the allocator marks the VM
assignable, excluding the one-time allocator deploy; statistics are medians
and interquartile ranges across a run's VMs. Script, metadata, and raw data
are in `paper/fig2-harness/`.

From a cold start, a ready 30-seat pool takes about seven minutes. At 5 to 60
seats the per-client median readiness time stayed near five minutes. The
150-seat run, the size of the largest event in \autoref{tbl:events}, had all
VMs ready 11 minutes after the launch command with a per-client median of
about six and a half minutes; its infrastructure apply took 249 s against 83 s
at 30 seats, while per-client boot time grew only modestly. All 255 VMs
across the five pools reached ready (\autoref{fig:benchmark}C, with counts
annotated above each bar). Ten (two at 10 seats, eight at 150) needed one
automatic reboot after reporting a startup
failure at the same point during the client-image pull, pointing to a
transient registry failure rather than faulty machines; all ten were ready
after the second boot.

![Workshop-scale benchmark, 5 to 150 seats. (A) Wall-clock to prepare one
30-seat workshop: allocator deploy (126 s), client-VM apply (83 s), and boot
until all 30 VMs were ready (229 s). (B) Per-client readiness time by pool size
N. (C) Client VM outcomes per pool as a share of the pool: VMs that reached ready directly,
after one automatic reboot, or failed.\label{fig:benchmark}](fig2.png)

# Research impact statement

LabLink was built to run SLEAP [@pereira2022sleap] workshops and has
delivered on-demand GPU desktops at 15 events between 2024 and 2026
(\autoref{tbl:events}), from K–12 students to faculty, totaling approximately 600 attendances. The 2024 events ran on LabLink's earlier Chrome Remote
Desktop-based implementation, which predates the current repository. Each
event posed the problem in the Statement of need: heterogeneous laptops, many
without a GPU, and a few hours to teach a GPU-dependent graphical tool;
nothing was installed on participants' machines.

LabLink's contribution to research is dissemination: installation
is a documented barrier to adoption [@mangul2019installability], and for
GPU-dependent tools a hands-on workshop is often a researcher's first chance
to try the software. The approach generalizes beyond SLEAP: LabLink
environments for Cellpose [@stringer2021cellpose], Kilosort4
[@pachitariu2024kilosort4], idtracker.ai [@romeroferrero2019idtracker], and
DeepLabCut [@mathis2018deeplabcut] each required changing only the
configuration and startup script, and any GPU-dependent research tool can
be taught the same way.

| Event                                                    | Date(s)         | Participants         | Location                                              |
| -------------------------------------------------------- | --------------- | -------------------- | ----------------------------------------------------- |
| Cosyne Main Tutorial – SLEAP                             | Feb 29, 2024    | ~150                 | Lisbon, Portugal                                      |
| University of Illinois Urbana–Champaign workshop         | Apr 2, 2024     | ~40                  | Urbana, IL, USA                                       |
| Keiller Leadership Academy STEM Day                      | May 30, 2024    | ~125 (K–12 students) | San Diego, CA, USA                                    |
| CAJAL Advanced Neuroscience Training Programme           | Jun 2024        | ~20                  | Champalimaud Centre for the Unknown, Lisbon, Portugal |
| Salk EDGE Summer Program                                 | Jul 24, 2024    | 3                    | La Jolla, CA, USA                                     |
| NYU Langone Neuroscience T32 Workshop                    | Aug 19, 2024    | ~25                  | New York, NY, USA                                     |
| Ellen Potter Research Connections                        | Apr 9–10, 2025  | ~20                  | Salk Institute, La Jolla, CA, USA                     |
| Bridges to the Future Symposium                          | May 28, 2025    | ~50                  | Salk Institute, La Jolla, CA, USA                     |
| CAJAL Advanced Neuroscience Training Programme           | Jun 8–27, 2025  | ~30                  | Champalimaud Centre for the Unknown, Lisbon, Portugal |
| Zagreb NeuroData Summer School                           | Jul 2025        | ~30                  | Online / Zagreb, Croatia                              |
| Salk EDGE Summer Program                                 | Jul 14–15, 2025 | 2                    | Salk Institute, La Jolla, CA, USA                     |
| Computer Vision for Biologists                           | Sep 1–12, 2025  | ~30                  | University of California Davis, CA, USA               |
| Introduction to Multi-Animal Pose Tracking (US-RSE 2025) | Oct 6, 2025     | ~30                  | Philadelphia, PA, USA                                 |
| Short course on machine learning applications            | Oct 13–17, 2025 | ~30                  | Jackson Laboratory, Bar Harbor, ME, USA               |
| CAJAL Advanced Neuroscience Training Programme           | Jun 10, 2026    | 18                   | Champalimaud Centre for the Unknown, Lisbon, Portugal |

Table: Workshops and courses delivered on LabLink, 2024–2026. Participant counts marked ~ are organizer estimates.\label{tbl:events}

# AI usage disclosure

Claude Opus 5 and Claude Fable 5.1 (Anthropic), through Claude Code, assisted
with both the software and this manuscript. The human authors designed and
wrote the architecture and initial implementation; Claude Code later drafted
code and documentation, which the authors reviewed and validated with the
automated test suites and in live deployments. The authors drafted the paper;
Claude reviewed and shortened the text, checked citations, and helped
assemble the benchmark figure, which the committed script regenerates from
recorded run data. All text and figures were reviewed by the authors.

# Acknowledgements

This work was supported by the NIH/BRAIN Initiative RF1 award under grant
number 1RF1MH132653-01. We thank the open-source projects that made this work
possible, including OpenTofu, Docker, KasmVNC, and PostgreSQL.

# References

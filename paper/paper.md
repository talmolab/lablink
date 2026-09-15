---
title: "LabLink: Cloud-based virtual teaching lab accessible through the browser"
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

Quantitative biology increasingly relies on GPU-accelerated deep learning tools with graphical interfaces,
but teaching them hands-on is hard: installing complex software environments consumes the opening hours
of a workshop, and many participants' laptops have no GPU at all. LabLink is an open-source
Infrastructure-as-Code (IaC) platform with which a research group can deploy and manage reproducible
GPU computing environments in its own Amazon Web Services (AWS) account or on hardware it already owns.
A lightweight allocator service manages one machine per participant, provisioned in the
cloud or registered from the lab's own hardware, and monitors its health; each workshop participant claims a seat by entering their
email on a web page and lands in a full Linux desktop with the instructor's software preinstalled,
running in a browser tab (\autoref{fig:overview}). LabLink removes per-participant installation entirely:
in our benchmark, a 30-seat pool was ready about seven minutes after a cold start. The platform
has supported approximately 600 users across 15 events, from K–12 students to faculty researchers.

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
resolving complex dependency stacks, GPU drivers, and operating-system-specific
configuration [@mangul2019installability]; a classroom presents a different
failure mode per laptop, and the first hours of a workshop are routinely lost
to setup. Worse, many participants have no local GPU, so even a successful
installation leaves them unable to run training or inference.

The common workarounds each sacrifice something essential. Asking participants
to preinstall shifts the burden onto the least experienced users. Shared
teaching servers require institutional infrastructure and maintenance effort
most labs do not have, and cloud notebooks solve hardware access but cannot
host interactive graphical applications. LabLink closes this gap: a research
lab can set up a group of identical, isolated, GPU-backed Linux desktops in
its own cloud account, hand each participant one link, and tear everything
down when the workshop ends. LabLink targets maintainers and instructors of
GPU-dependent scientific software who need to give a room of participants
working environments without per-laptop setup or institutional computing
infrastructure.

# State of the field

Domain platforms such as brainlife.io [@hayashi2024brainlife], Neurodesk
[@renton2024neurodesk], and brainchop [@masoud2023brainchop] deliver
cloud-based or in-browser neuroimaging environments. NeuroCAAS
[@abe2022neurocaas] applies infrastructure-as-code to neuroscience but serves
reproducible analyses as batch jobs rather than interactive desktops. These
serve their target domains well, but each is organized around its own
application catalog rather than around software the instructor packages
themselves.

General-purpose teaching infrastructure is notebook-centric. JupyterHub
[@jupyterhub] can stream a Linux desktop through extensions such as
jupyter-remote-desktop-proxy [@jupyterdesktopproxy], but this is a
standing service that someone must keep running. A small class can run one
on a single server with The Littlest JupyterHub [@tljh]. Larger classes, and
BinderHub [@jupyter2018binder], need a Kubernetes cluster. Providers such as
2i2c [@twoi2c] will host the hub instead. None of them automates the event
itself: adding GPU machines, admitting participants, and tearing everything
down are left to the operator of a persistent hub.
Browser development environments such as GitHub Codespaces, Gitpod, and
Coder offer editors and terminals rather than GPU desktops for graphical
applications. The Galaxy project's Training Infrastructure
as a Service [@rasche2023tiaas] has supported over 500 training events with
more than 24,000 learners but serves Galaxy workflows on shared public servers, not
an instructor's own software. Google Colab offers GPUs without operational
burden, but imposes session limits, supports only notebooks, and gives the
instructor no control over the environment.

Browser-based remote desktops themselves are well established: Apache
Guacamole [@guacamole] gateways a browser to existing machines, Open
OnDemand [@hudak2018openondemand] delivers graphical desktops from an
institutional HPC cluster with center-level administration, and Kasm
Workspaces [@kasmworkspaces] orchestrates containerized desktops as a standing, account-based
service that an administrator installs and maintains.

Cloud vendors also serve this niche, as standing, account-based services.
Azure Lab Services [@azurelabservices] provisions per-student VM pools with
scheduled start and stop, but has been closed to new customers since July 2024
and retires in June 2027. Amazon WorkSpaces and WorkSpaces Applications (formerly
AppStream 2.0) [@awsworkspaces] stream managed, GPU-capable desktops and
applications from an AWS account. Both are also bound to their vendor's cloud,
whereas a LabLink deployment can run entirely on GPU machines the lab already
owns.

LabLink's contribution is therefore not the browser desktop but the
integration around it: reproducible provisioning of one GPU machine per
participant in infrastructure the operator owns, desktops running
instructor-packaged software, accountless email-based seat claiming,
real-time health monitoring with automatic recovery, and teardown when the
event ends. We wrote new software because the missing piece is the workshop
lifecycle itself, not the desktop or notebook underneath it: existing platforms
are built as standing services an administrator maintains, whereas a LabLink
deployment is created for one event and destroyed afterward.

# Software design

LabLink's architecture centers on two components: an **allocator** that
manages a group of client machines, and a **client service** that runs on
each machine. The allocator is a Flask [@flask] service that owns a PostgreSQL [@postgresql]
database of client machines (cloud VMs it provisions by running OpenTofu [@opentofu], an open-source
Terraform-compatible IaC tool, as asynchronous background operations, or
machines that the lab owns) and
assigns each participant who claims a seat to an unclaimed machine. It also serves
as an admin dashboard with per-machine status and logs, and can destroy
client machines at a scheduled time so a forgotten pool does not outlive its
event. Each client machine
runs one Docker [@merkel2014docker] container built from the instructor's image, which hosts
both the KasmVNC [@kasmvnc] desktop the participant sees and the client service
reporting the machine's state. Giving each participant a whole machine
rather than a slice of a shared server trades infrastructure cost for
isolation (one participant's crashed session or saturated GPU affects only
their own seat). At AWS on-demand prices in us-west-2 [@awsec2pricing], a
`g4dn.xlarge` seat costs about \$0.53 per hour, so the compute for a four-hour, 30-seat workshop comes
to about \$63, roughly \$2 per participant. The two components communicate
over a simple contract:
the client service registers its machine with the allocator, then reports
heartbeats, GPU health, and seat status through client-initiated REST API
calls. The client machine's KasmVNC session is streamed over WebSockets
and proxied through the allocator's nginx [@nginx], making the allocator the deployment's
single participant-facing endpoint.

## Deployment

Deployment is deliberately decoupled from these components: the OpenTofu
definition of the allocator's infrastructure lives in a separate template
repository (https://github.com/talmolab/lablink-template). Operators deploy
either through the CLI (`lablink-cli`) — an interactive configuration
wizard plus commands to provision and monitor machines — or, for
version-controlled, reviewable infrastructure changes, by forking the
template repository and using its GitHub Actions workflows. Both paths
deploy the same allocator image and infrastructure definition. All three
packages ship automated test suites that run in continuous integration on
every change.

The `manual` provider extends the same client–allocator contract to
bring-your-own (BYO) machines, such as lab workstations or containers on an
institutional GPU scheduler. Because all control traffic is outbound HTTP
and the allocator itself can be published through an outbound tunnel,
neither side needs inbound firewall rules, and several desktop transport
options (direct LAN connection, a WireGuard-based mesh overlay, or a
client-initiated WebSocket tunnel) cover firewalled and fully on-premises
topologies.

## Security

The security model follows from this topology. The allocator is the only
participant-facing endpoint, and desktops are reached only through its
proxy. TLS is a configuration option (Let's Encrypt, Cloudflare, or AWS
Certificate Manager), not a default; a deployment reached by bare IP address
runs over plain HTTP. Admin pages and operator APIs require operator
credentials; client machines authenticate with per-machine secrets minted at
registration and never hold database or admin credentials.

The seat-claim page is deliberately unauthenticated: an email address labels
a seat rather than authenticating a user, and no passcode or rate limit gates
it. This is acceptable only because a deployment is short-lived with a fixed
pool. A leaked link can exhaust seats but cannot provision machines, one email
address holds at most one seat, and scheduled destruction bounds the deployment's lifetime.
Claiming a seat rotates that desktop's password and binds the browser to a
signed session cookie, so participants cannot open one another's seats.
Participants have administrative rights inside their desktop container but
not on the host, and on AWS a client machine accepts no inbound connections
other than operator SSH. The address is format-checked but never verified,
so any email-shaped token serves as a seat label; it is held only within the
deployment (its database and service logs) and is destroyed with it.

## Adaptability

Adapting a deployment to new software means changing two files: a YAML
configuration that names the Docker image, and a startup script that installs
the instructor's software and stages tutorial data as the client container
boots.

## Benchmark

Workshop-scale behavior is measured in \autoref{fig:benchmark}. From a cold
start, a ready 30-seat pool takes about seven minutes. In single runs at pool
sizes of 5, 10, 30, and 60 VMs, the per-VM median time from the pool-launch
command to a VM ready to be assigned stayed around five minutes. A 150-seat
run, the size of the largest event in \autoref{tbl:events}, had all 150 VMs
ready 11 minutes after the launch command, with a per-VM median of about six
and a half minutes; its infrastructure apply took 249 s against 83 s at 30
seats, so the apply phase grows with pool size while per-VM boot time grows
only modestly.

![Workshop-scale benchmark: a LabLink deployment scaled from 5 to 150 seats
on `g4dn.xlarge` instances (us-west-2), one run per pool size. The pools of 5
to 60 seats share one pinned client-image digest; the 150-seat pool ran twelve
days later on the 0.4.0 release image. (A) Wall-clock to prepare one 30-seat
workshop: allocator deploy (126 s), client-VM apply (83 s), and boot until
all 30 VMs were ready (229 s) — a ready pool in about 7 min from nothing.
(B) Per-VM readiness time by pool size N, measured from the operator's single
pool-launch command until the allocator marks each VM ready to be assigned;
bars are medians across the pool's VMs, whiskers the interquartile range
(IQR) across those VMs within the run, not across runs. B excludes the
one-time allocator deploy. (C) VM outcomes per pool: the number of VMs that
reached ready directly, after one automatic reboot, or failed. All 255 VMs
across the five pools reached ready; ten required one automatic reboot (two
at N = 10, eight at N = 150), exercising the recovery path. The figure script, run metadata,
and raw data are in `paper/fig2-harness/` in the LabLink
repository.\label{fig:benchmark}](fig2.png)

# Research impact statement

LabLink was built to run SLEAP [@pereira2022sleap] workshops and has since
delivered on-demand GPU desktops at 15 events with approximately 600
participants between 2024 and 2026 (\autoref{tbl:events}), spanning audiences from K–12
students to graduate students and faculty.

LabLink's contribution to research runs through dissemination. Installation
is a documented barrier to adopting research software
[@mangul2019installability]; for GPU-dependent tools, a hands-on workshop is
often a researcher's first opportunity to try the software at all. By
removing setup for an entire classroom at once, LabLink converts the hours a
workshop would otherwise spend on installation into supervised practice of
the complete GPU workflow, on hardware every participant can run it on, with
the instructor present when something goes wrong.

This generalizes beyond SLEAP. LabLink environments for Cellpose
[@stringer2021cellpose], Kilosort4 [@pachitariu2024kilosort4], idtracker.ai
[@romeroferrero2019idtracker], and DeepLabCut [@mathis2018deeplabcut] each
required changing only the configuration and startup script, and any group that maintains a
GPU-dependent research tool can hand its users a working GPU desktop the same
way.

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

Claude Opus 5 (Anthropic) was used in developing both the software and this
manuscript. The architecture and initial implementation of LabLink were
designed and implemented by the human authors. Claude Code was later used to draft
code and documentation. The paper was drafted by the human authors, and Claude
Fable 5 was used to review the text and to help assemble metrics and figures.
All generated code, documentation, and figures were reviewed by the human authors
and validated with the automated test suites and in live deployments.

# Acknowledgements

This work was supported by the NIH/BRAIN Initiative RF1 award under grant
number 1RF1MH132653-01. We want to acknowledge the open-source projects that
made this work possible, including OpenTofu, Docker, KasmVNC, and PostgreSQL.

# References

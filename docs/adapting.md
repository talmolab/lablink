# Adapting LabLink for Your Research Software

LabLink serves a client container with a browser desktop and a client agent.
The agent must report `running` before the allocator can assign the machine.
Choose the smallest change that supplies your software: a startup script for
installation at boot, or a custom client image for a reproducible environment.

## Option 0: Startup Script

`startup_script` runs a shell script inside each client container before it
reports `running`. It can install packages or prepare workshop files without
building an image. For example, a script that installs `ffmpeg`:

```bash
#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y ffmpeg
```

Save it as `lablink-infrastructure/config/custom-startup.sh` in a template
repository, or as `~/.lablink/custom-startup.sh` for a CLI deployment. The
CLI copies that file into its deployment working directory. Set:

```yaml
startup_script:
  enabled: true
  path: "config/custom-startup.sh"
  on_error: "fail"
  max_attempts: 3
  base_delay_seconds: 30
  success_check: "command -v ffmpeg"
```

The script and success check are retried on failure, so make them safe to run
more than once. With `on_error: fail`, a final failure stops that client from
reporting `running`. Use `on_error: continue` only when participants can work
without the script's result. See
[Startup Script Options](configuration.md#startup-script-options-startup_script).

## Option 1: Extend the Client Image

Use a custom image when installation takes too long at each boot or when you
need to test and pin the whole desktop environment. Extend a published
`lablink-client-base-image` tag so you retain KasmVNC, the client agent, and
`/home/client/start.sh`. A from-scratch image needs to recreate all of those
pieces; installing `lablink-client-service` alone is insufficient.

For a project that only adds tutorial files:

```dockerfile
FROM ghcr.io/talmolab/lablink-client-base-image:linux-amd64-0.4.0
COPY --chown=client:client tutorial/ /home/client/tutorial/
```

Build for the client VM's architecture, smoke-test the content, and push the
image to a registry the VM can pull:

```bash
docker build --platform linux/amd64 -t ghcr.io/your-org/tutorial:0.1.0 .
docker run --rm --platform linux/amd64 --entrypoint sh \
  ghcr.io/your-org/tutorial:0.1.0 -c 'test -d /home/client/tutorial'
docker push ghcr.io/your-org/tutorial:0.1.0
```

The client VM's boot script pulls images without registry credentials. Make
the image publicly readable, or use a custom AMI with a registry credential
helper. Avoid embedding long-lived registry secrets in the image itself.

## Configure and Test

Set the image and optional public repository in the same `config.yaml` used
by the CLI or template path:

```yaml
machine:
  machine_type: "g4dn.xlarge"
  image: "ghcr.io/your-org/tutorial:0.1.0"
  ami_id: ""  # resolve the default compatible AMI in the chosen AWS region
  repository: "https://github.com/your-org/workshop-materials.git"
  software: "your-tool"
```

`machine.machine_type` selects the client EC2 type; the allocator remains
`t3.large` in the template. `machine.repository` is cloned into the client
desktop at startup and can be omitted. `machine.software` identifies the
configured software to the client service. The empty `ami_id` asks OpenTofu
to resolve the default Deep Learning Base AMI in the region; run
`lablink doctor` to check it before deploying.

The image smoke test checks only that the image contains what you expect. To
test registration, the desktop, and connectivity together on your own
hardware, follow [Bring-Your-Own Clients](cli/byo-clients.md) with
`provider: manual`. A bare allocator `docker run` lacks the config and
registration flow needed for that test.

For AWS, use [First Deployment](cli/first-deployment.md) or the
[template quickstart](quickstart-template.md). After launching a client,
check `lablink status` and `lablink logs` (or the admin logs page) before
inviting participants.

## Custom AMI

Use `machine.ami_id` when you need a specific host image. For GPU clients,
it must provide Docker, the NVIDIA driver, and the NVIDIA container runtime;
the client boot script does not install those components. A stock Ubuntu
AMI alone will not work. Make the AMI available in the deployment region and
run `lablink doctor` to verify its ID there. Changing the Docker image in
`machine.image` usually avoids maintaining a custom AMI.

## Private Registries and Multiple Workloads

Private image pulls need credentials on the client host before the boot
script runs. The standard deployment does not configure them. A public
image is the simplest path; a custom AMI with a credential helper is an
advanced alternative.

For separate workloads, keep separate config files and pass `--config` to
`lablink deploy`, `lablink status`, and other CLI commands. The allocator
uses one `machine` configuration per deployment; `machine.software` is not a
switch that installs several applications by itself.

For image startup problems, see
[Custom Client Images](troubleshooting.md#custom-client-images).

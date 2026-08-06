# Troubleshooting

**First step:** run the built-in checks and read the output before anything else.

```bash
lablink doctor          # operator-side prerequisites, for the provider you configured
lablink status          # is the allocator up, and what does it think its VMs are doing
lablink client doctor   # on a BYO client box: registration, container, log shipper
```

`lablink doctor` branches on your provider — Docker checks under `manual`, and Terraform, AWS credentials, S3 and AMI checks under `aws`. Most problems below are named in its output.

!!! info "Which port?"
    The allocator container listens on **5000**. Ports 80 and 443 only answer when Caddy is running, which happens for `ssl.provider: letsencrypt` and `cloudflare` only. With `none` or `acm`, `curl localhost:80` on the instance will fail even though the allocator is perfectly healthy — use `curl localhost:5000`.

## Docker

??? note "Permission denied connecting to the Docker daemon"
    ```
    Got permission denied while trying to connect to the Docker daemon socket
    ```

    Add yourself to the `docker` group:

    ```bash
    sudo usermod -aG docker $USER
    newgrp docker
    docker ps
    ```

??? note "Cannot connect to the Docker daemon"
    ```
    Cannot connect to the Docker daemon at unix:///var/run/docker.sock
    ```

    Linux — start the service:

    ```bash
    sudo systemctl start docker
    sudo systemctl enable docker
    ```

    macOS / Windows — start Docker Desktop.

## SSH access

??? note "Permission denied (publickey)"
    In order, the three things that cause this:

    1. **Key permissions too open** — SSH silently refuses a world-readable key.
       ```bash
       chmod 600 ~/lablink-key.pem
       ls -l ~/lablink-key.pem      # -rw-------
       ```
    2. **Wrong key** — re-extract it from Terraform state.
       ```bash
       terraform output -raw private_key_pem > ~/lablink-key.pem
       chmod 600 ~/lablink-key.pem
       ```
    3. **Wrong user** — it's `ubuntu` on the Ubuntu AMIs LabLink uses, not `ec2-user`.

??? note "SSH connection timed out"
    Timeout means the packets aren't arriving at all — a closed port or a stopped instance, not an auth problem.

    ```bash
    aws ec2 describe-instances --instance-ids <id> \
      --query 'Reservations[0].Instances[0].State.Name'
    terraform output allocator_public_ip
    aws ec2 authorize-security-group-ingress \
      --group-id <sg-id> --protocol tcp --port 22 --cidr 0.0.0.0/0
    ```

    Also check the VPC's network ACLs allow inbound and outbound on 22.

## Deploying (AWS provider)

??? note "Terraform init fails: bucket does not exist"
    `lablink setup` creates the S3 state bucket and the DynamoDB lock table for you. If you skipped it, create the bucket by hand:

    ```bash
    aws s3 mb s3://tf-state-lablink-allocator-bucket --region us-west-2
    aws s3api put-bucket-versioning \
      --bucket tf-state-lablink-allocator-bucket \
      --versioning-configuration Status=Enabled
    terraform init
    ```

??? note "Error acquiring the state lock"
    A previous Terraform run died without releasing its DynamoDB lock.

    First make sure nothing is actually still running:

    ```bash
    aws dynamodb scan --table-name lock-table --region us-west-2
    ps aux | grep terraform
    ```

    Entries with an `Info` field are real locks; the rest are digests. Copy the exact `LockID` — it does **not** always carry an `-md5` suffix — and delete it:

    ```bash
    aws dynamodb delete-item \
        --table-name lock-table \
        --key '{"LockID":{"S":"<exact-lock-id-from-scan>"}}' \
        --region us-west-2
    ```

    On Windows PowerShell, put the key in a `key.json` file and pass `--key file://key.json`.

    Common lock paths:

    - Infrastructure: `tf-state-lablink-allocator-bucket/<env>/terraform.tfstate`
    - Client VMs: `tf-state-lablink-allocator-bucket/<env>/client/terraform.tfstate`

    If you get `AccessDeniedException: not authorized to perform: dynamodb:GetItem`, the allocator's IAM role is missing `dynamodb:GetItem`, `PutItem` and `DeleteItem` on `table/lock-table`. Add them and redeploy.

    **Prevention:** let Terraform runs finish. Don't terminate instances from the console mid-apply, and use the destroy workflow rather than deleting resources by hand.

??? note "Resource already exists"
    Either import it, delete it, or deploy under a different suffix:

    ```bash
    terraform import aws_security_group.lablink sg-xxxxx
    # or
    aws ec2 terminate-instances --instance-ids i-xxxxx
    # or change resource_suffix: -dev / -test / -prod
    ```

??? note "Resources won't destroy cleanly"
    Usually a dependency still attached — network interfaces, an associated Elastic IP, or security groups referencing each other. Terminate instances first, wait, then remove the group:

    ```bash
    aws ec2 terminate-instances --instance-ids i-xxxxx
    aws ec2 wait instance-terminated --instance-ids i-xxxxx
    aws ec2 delete-security-group --group-id sg-xxxxx
    ```

??? note "GitHub Actions: could not assume role with OIDC"
    ```bash
    aws iam list-open-id-connect-providers
    aws iam get-role --role-name github-lablink-deploy \
      --query 'Role.AssumeRolePolicyDocument'
    ```

    The trust policy must name your repository (`repo:<owner>/<repo>:*`), and the role ARN in the workflow must match your account ID.

??? note "GitHub Actions: workflow won't trigger"
    Check the branch name and path filters against the workflow's `on:` block, confirm Actions are enabled for the repository, and validate the YAML:

    ```bash
    yamllint .github/workflows/*.yml
    ```

## Reaching the allocator

??? note "Browser shows connection refused"
    Work outward from the container:

    ```bash
    ssh -i ~/lablink-key.pem ubuntu@<ip>
    sudo docker ps                    # is it running?
    sudo docker logs -f <container>   # did it crash on startup?
    curl localhost:5000               # does it answer locally?
    ```

    If it answers locally but not from outside, it's the security group. The allocator's group should allow 22, 5000, and — when Caddy is in play — 80 and 443:

    ```bash
    aws ec2 authorize-security-group-ingress \
      --group-id <sg-id> --protocol tcp --port 5000 --cidr 0.0.0.0/0
    ```

??? note "Browser cannot reach the HTTP site (no SSL provider)"
    Symptoms: "This site can't be reached", `ERR_CONNECTION_REFUSED` on a deployment using `ssl.provider: "none"`.

    Your browser cached an HSTS policy from a previous HTTPS deployment on the same hostname, so it silently upgrades to HTTPS — and port 443 is closed.

    Quickest workarounds: use a private/incognito window, or hit the IP directly.

    To clear it properly:

    === "Chrome / Edge"
        1. Open `chrome://net-internals/#hsts` (`edge://` on Edge)
        2. Under **Delete domain security policies**, enter your domain
        3. Click **Delete**, then reload with an explicit `http://`

    === "Firefox"
        1. Close all Firefox windows
        2. Delete `SiteSecurityServiceState.txt` from your profile directory
           (`~/Library/Application Support/Firefox/Profiles/` on macOS,
           `%APPDATA%\Mozilla\Firefox\Profiles\` on Windows,
           `~/.mozilla/firefox/` on Linux)
        3. Restart and reload with an explicit `http://`

    === "Safari"
        1. Quit Safari
        2. `rm ~/Library/Cookies/HSTS.plist`
        3. Restart and reload with an explicit `http://`

    Expected behaviour with `ssl.provider: "none"` is a "Not Secure" badge — no certificate is issued and traffic is unencrypted. For HTTPS, set `ssl.provider` to `letsencrypt`, `cloudflare` or `acm`. See [Configuration → SSL Options](configuration.md#ssltls-options-ssl).

??? note "HTTP works but HTTPS doesn't"
    Caddy cannot get a certificate until DNS resolves to the allocator, so check that first:

    ```bash
    nslookup <your-domain> 8.8.8.8
    sudo systemctl status caddy
    sudo journalctl -u caddy -f
    ```

    In the Caddy log, `certificate obtained successfully` means it worked; `challenge failed` means DNS isn't ready; `timeout` means ports 80/443 aren't reachable. Caddy retries every 2 minutes on its own, so a few minutes of patience often fixes it.

    Verify the Caddyfile proxies to the container's real port:

    ```bash
    cat /etc/caddy/Caddyfile
    # <your-domain> {
    #     reverse_proxy localhost:5000
    # }
    sudo systemctl restart caddy
    ```

    !!! warning "Let's Encrypt rate limit"
        Five duplicate certificates per domain per week. Redeploying the same test hostname repeatedly exhausts the quota and the site serves a TLS error until it resets. Use a fresh hostname for throwaway deployments, or `ssl.provider: "none"` while iterating.

??? note "Domain doesn't resolve to the allocator"
    ```bash
    # Does the record exist?
    aws route53 list-resource-record-sets --hosted-zone-id <zone-id> \
      --query "ResourceRecordSets[?Name=='<your-domain>.']"

    # Does it match the actual IP?
    terraform output allocator_public_ip
    dig <your-domain> +short
    ```

    If the record is missing, re-run `terraform apply`. If it exists but isn't propagating, give it 5–15 minutes and flush your local cache (`sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder` on macOS, `sudo systemd-resolve --flush-caches` on Linux, `ipconfig /flushdns` on Windows).

??? note "DNS record landed in the wrong hosted zone"
    Terraform's zone lookup matched the parent zone (e.g. `example.com` instead of `lablink.example.com`). Pin it explicitly:

    ```yaml
    dns:
      enabled: true
      terraform_managed: true
      domain: "test.lablink.example.com"
      zone_id: "Z0123456789ABCDEFGHIJ"   # force the correct zone
    ```

    Delete the stray record from the wrong zone, then re-apply.

??? note "Verifying a deployment end to end"
    The template repo ships a script that checks DNS, HTTP, and SSL together. It lives in `scripts/`, not `lablink-infrastructure/`:

    ```bash
    ./scripts/verify-deployment.sh prod          # reads config.yaml + terraform outputs
    ./scripts/verify-deployment.sh <domain> <ip> # or pass them explicitly
    ./scripts/verify-deployment.sh --ci prod     # no ANSI colors, for CI logs
    ```

    Green checks are pass, yellow warnings usually mean "not ready yet — wait and retry", red is a real failure. The three common ones are a DNS timeout (wait longer), HTTP not responding (check the allocator container logs), and SSL not ready (check the Caddy logs).

??? note "NS delegation not working"
    `nslookup` returns your registrar's nameservers instead of AWS, so records in Route53 are never consulted.

    ```bash
    dig NS lablink.example.com          # should list four awsdns nameservers
    aws route53 get-hosted-zone --id <zone-id> --query 'DelegationSet.NameServers'
    ```

    Add those four as NS records for the `lablink` subdomain at whoever hosts the parent domain, TTL 300, then re-check after 5–15 minutes.

    If you have both a parent and child zone in Route53 fighting each other, keep the one LabLink manages and delete the duplicate — `aws route53 list-hosted-zones --query 'HostedZones[*].[Name,Id]' --output table` shows them all.

## Client VMs (AWS provider)

??? note "Clicking Create VMs does nothing"
    ```bash
    sudo docker logs -f <allocator-container>
    sudo docker exec <allocator-container> aws sts get-caller-identity
    sudo docker exec <allocator-container> terraform version
    ```

    If `get-caller-identity` fails, the allocator's IAM instance profile isn't attached or lacks EC2 permissions (`RunInstances`, `DescribeInstances`) and VPC permissions (`CreateSecurityGroup`).

    To run Terraform by hand inside the container:

    ```bash
    sudo docker exec -it <allocator-container> bash
    cd /app/.venv/lib/python*/site-packages/lablink_allocator_service/terraform
    terraform init && terraform plan
    ```

??? note "VM created but never appears in the allocator"
    Clients **register themselves** — the allocator does not insert rows when Terraform finishes. Each client posts to `/api/v1/clients/register`, and the allocator stores its hostname alongside an argon2 hash of a freshly minted `client_secret`. A VM that never registers is a VM that never reached that endpoint.

    ```bash
    # What the allocator has
    sudo docker exec <allocator-container> psql -U lablink -d lablink_db \
      -c "SELECT hostname, status, inuse FROM vms;"

    # What the allocator saw
    sudo docker logs <allocator-container> | grep -E "clients/register|heartbeat"

    # What the client tried
    ssh -i ~/lablink-key.pem ubuntu@<client-vm-ip>
    sudo docker logs <client-container>

    # Can the client reach the allocator at all?
    curl -i http://<allocator-ip>:5000/api/health
    ```

    If `/api/health` fails from the client, stop debugging the client — it's the security group or the allocator's listening port.

    !!! danger "Don't INSERT rows by hand"
        A row created with just `(hostname, inuse)` has a null `client_secret_hash`, so that client can never authenticate for heartbeats, status or logs. It will look present in the admin panel and be permanently broken. Let the client register, or re-provision it.

??? note "Failed VMs aren't being rebooted"
    The allocator runs an `AutoRebootService` that sweeps every 60 seconds for VMs that are in `error`, `running` but GPU-`Unhealthy`, stuck `initializing` over 25 minutes, stuck `rebooting` over 10 minutes, or `running` but silent for 3 minutes with no heartbeat.

    It tries an SSH hard reboot (`sudo cloud-init clean && sudo reboot`), then an EC2 stop/start if SSH is unreachable. **Max 3 attempts per VM**, 300s cooldown between them.

    ```bash
    sudo docker logs <allocator-container> | grep -i reboot

    sudo docker exec <allocator-container> psql -U lablink -d lablink_db -c \
      "SELECT hostname, status, reboot_count, last_reboot_time FROM vms WHERE reboot_count >= 3;"
    ```

    There is no reboot API endpoint. To re-arm a VM that exhausted its attempts, reset it and let the next sweep pick it up:

    ```sql
    UPDATE vms SET reboot_count = 0, status = 'error' WHERE hostname = '<hostname>';
    ```

    To reboot out of band, use the EC2 console or `aws ec2 reboot-instances`.

    !!! note "BYO boxes are never rebooted"
        Only providers that can recover hosts participate. The `manual` provider can't, so bring-your-own machines are left alone.

??? note "CUDA not available on a client VM"
    ```bash
    ssh -i ~/lablink-key.pem ubuntu@<client-vm-ip>
    nvidia-smi
    docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
    cat /etc/docker/daemon.json    # expects "default-runtime": "nvidia"
    ```

    If `nvidia-smi` itself fails, the AMI has no drivers — use a GPU-enabled AMI. Also confirm the instance type actually has a GPU; a `t3.large` never will.

## Bring-your-own clients (manual provider)

??? note "Start here: `lablink client doctor`"
    Run it **on the client box**. It checks three things — that `~/.lablink/client.env` exists with this box's credentials, that the `lablink-client` container is running, and that the log shipper is forwarding to the allocator.

    Most failures are fixed by re-running `lablink client register`. See [Bring-Your-Own Clients](cli/byo-clients.md).

??? note "The client registers but participants can't reach the desktop"
    Almost always the wrong `manual.connectivity` mode for your network:

    - `lan_direct` puts the participant's browser onto the client's LAN IP. It **cannot** serve off-LAN participants, no matter what exposure mode you pair it with.
    - `mesh_overlay` joins the client to a Tailscale tailnet and proxies the byte path through the allocator's nginx.
    - `reverse_tunnel` has the client dial out and hold one connection open — for networks that won't carry Tailscale or boxes that can't accept inbound connections.

    See [Pick a connectivity mode](cli/byo-clients.md#pick-a-connectivity-mode).

??? note "A mesh-overlay client looks healthy but is unreachable"
    Re-registering a `mesh_overlay` client mints a **new** Tailscale node. MagicDNS suffixes the name (`-1`, `-2`, …) because the old node is offline but still holds the original name, so the allocator's stored hostname points at a machine that no longer answers — while the client's own logs look perfectly fine.

    Delete the stale machine in the Tailscale admin console, then re-register. Use `lablink client reset-overlay` when you deliberately want a fresh node identity; note it requires the `lablink-client` container to be gone first, since Docker won't remove an attached volume.

??? note "Allocator compose stack won't come up"
    ```bash
    docker compose ps
    docker compose logs -f allocator
    curl -i http://localhost:5000/api/health
    ```

    `lablink doctor` under the `manual` provider checks the Docker side for you.

## Inside the allocator

??? note "Cannot connect to PostgreSQL"
    `psycopg2.OperationalError: could not connect to server`. The container's `start.sh` starts Postgres and blocks on `pg_isready` before Flask boots, so a refused connection normally means the cluster died rather than that it was never started.

    ```bash
    sudo docker exec <container> pg_isready -U lablink
    sudo docker exec <container> psql -U lablink -d lablink_db -c "SELECT 1;"
    sudo docker exec <container> tail -f /var/log/postgresql/postgresql-*-main.log
    ```

    To restart the cluster in place:

    ```bash
    sudo docker exec -it <container> pg_ctlcluster 17 main restart
    ```

??? note "Running out of database connections"
    The allocator reports its own connection usage — check `/admin` (a line under the title) or hit the endpoint directly:

    ```bash
    curl -u admin:<password> http://<allocator>:5000/api/health/connections
    ```

    At the critical level, new connections can be refused, which fails VM registration and admin actions. Raise Postgres `max_connections` and `LABLINK_DB_POOL_MAX_SIZE` together, and check for connections stuck idle in transaction.

??? note "Container runs but Flask doesn't start"
    ```bash
    sudo docker logs <container>          # port in use, import error, bad config?
    sudo docker exec <container> cat /app/config/config.yaml
    sudo netstat -tulpn | grep 5000
    sudo docker restart <container>
    ```

    A config that fails schema validation stops the app before it serves anything — the log names the offending key.

## Diagnostic commands

```bash
# Host health
df -h; free -h; top
sudo docker ps -a
sudo docker stats
sudo netstat -tulpn

# Allocator
curl localhost:5000/api/health
sudo docker logs -f <allocator-container>

# Database
sudo docker exec <container> pg_isready -U lablink
sudo docker exec <container> psql -U lablink -d lablink_db -c "SELECT hostname, status, inuse FROM vms;"

# AWS reachability from inside the container
sudo docker exec <container> aws sts get-caller-identity
```

## Before you ask for help

- [ ] `lablink doctor` run, output read
- [ ] Container running (`docker ps`) and answering on `localhost:5000`
- [ ] Security group allows 22 and 5000, plus 80/443 if using Caddy
- [ ] SSH key is mode 600
- [ ] AWS credentials resolve (`aws sts get-caller-identity`)
- [ ] Terraform state not locked, S3 bucket exists
- [ ] Config passes validation — no unknown keys

**Still stuck?** Search [existing issues](https://github.com/talmolab/lablink/issues), then open a new one with the `lablink doctor` output, the relevant container logs, what you expected, and what you tried.

## Related documentation

- [Prerequisites](prerequisites.md) — what each deployment path actually needs
- [Bring-Your-Own Clients](cli/byo-clients.md) — the manual provider end to end
- [Configuration](configuration.md) — every config key and its valid values
- [Deployment](deployment.md) — deployment and teardown
- [Database](database.md) — schema and direct access
- [Security & Access](security.md) — auth, SSH, and SSL posture

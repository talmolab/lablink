# Workshop Guide

A step-by-step guide for running a hands-on workshop with LabLink, from setup to cleanup.

!!! info "Prerequisites"
    This guide assumes you have already [deployed LabLink](quickstart.md) and [configured it for your software](adapting.md).

## Before the Workshop

### 1. Create VMs

Spin up VMs ahead of time so they're ready when participants arrive. VMs take approximately 5 minutes to provision.

1. Navigate to the admin panel at `http://<allocator-ip>/admin`
2. Log in with your admin credentials
3. Click **"Create VMs"**
4. Enter the number of VMs to launch (one per participant, plus a few extras)
5. Click **"Launch VMs"**

![Create VMs dialog](assets/images/admin-create-vms.png)

!!! tip
    Create a few extra VMs beyond your expected headcount. You can always destroy unused ones later, but creating more mid-session takes 5 minutes.

### 2. Verify VMs Are Healthy

Wait for all VMs to show **"running"** status in the dashboard before the workshop begins.

![Admin panel overview](assets/images/admin-panel-overview.png)

The dashboard shows the following for each VM:

| Column | Description |
|--------|-------------|
| **Hostname** | VM instance identifier |
| **Health** | Overall VM health status (running, initializing, stopped) |
| **GPU Health** | GPU availability and CUDA status |
| **Logs** | Link to view startup and runtime logs for the VM |
| **Assigned CRD** | Chrome Remote Desktop connection link for the VM |
| **User Email** | Email of the participant assigned to the VM |

!!! warning "What if a VM is stuck?"
    If a VM stays in "initializing" for more than 10 minutes or shows "error" status, it will be automatically rebooted. Check the VM logs for details.

### 3. (Optional) Schedule Auto-Destruction

If your workshop has a fixed end time, schedule VMs to be automatically destroyed:

1. Set the desired destruction date and time in the admin panel
2. Confirm the schedule

![Scheduled destruction](assets/images/admin-scheduled-destruction.png)

This is useful as a safety net to avoid leaving VMs running (and incurring costs) if you forget to clean up manually.

## Share with Participants

### What to Share

Give participants the allocator URL:

```
http://<allocator-ip>
```

Or if you configured DNS:

```
https://lablink.yourdomain.com
```

### What Participants Do

1. Visit the URL in their browser
2. Enter their email address
3. They receive a Chrome Remote Desktop (CRD) link to their assigned VM
4. Click the link to open a full desktop with your software pre-installed

No installation, no setup -- participants only need a Chrome browser.

## During the Workshop

### Monitor the Dashboard

Keep the admin panel open to track participant activity:

![Admin panel](assets/images/admin-panel.png)

- **Health** column shows if VMs are running normally
- **GPU Health** confirms GPU availability for compute workloads
- **Assigned CRD** shows which participants have been assigned VMs
- **User Email** shows who is using each VM

### Adding More VMs

If more participants arrive than expected:

1. Click **"Create VMs"** in the admin panel
2. Enter the additional number needed
3. Click **"Launch VMs"**

New VMs are created without affecting existing running VMs. They'll be ready in about 5 minutes.

### Handling Issues

- **VM shows "error"**: The auto-reboot service will attempt to recover it automatically (up to 3 times). Check the logs link for details.
- **Participant can't connect**: Verify their VM shows "running" status and that the CRD link is assigned. Try having them refresh the allocator page to get a new link.
- **All VMs assigned**: Create additional VMs as described above.

## End of Workshop

### 1. Extract Participant Data

Before destroying VMs, download any files participants created:

1. Click **"Download User Data"** in the admin panel
2. The allocator collects files matching your configured extension (e.g., `.slp`) from each VM
3. A zip file downloads with all participant work

![Download user data](assets/images/admin-destroy-vms.png)

!!! warning "Do this before destroying VMs"
    Files are not recoverable after VMs are destroyed. Always extract data first.

The file extension to collect is configured in your `config.yaml`:

```yaml
machine:
  extension: "slp"
```

### 2. Destroy VMs

Once data is collected, tear down all VMs:

1. Click **"Destroy All VMs"** in the admin panel
2. Confirm the action

![Destroy All VMs](assets/images/admin-destroy-vms.png)

This terminates all client EC2 instances and clears VM records from the database.

## After the Workshop

### Destroy the Allocator (Optional)

If you don't need LabLink running until your next workshop, destroy the allocator infrastructure to stop incurring costs:

=== "Via GitHub Actions"

    Manually run the **Terraform Destroy** workflow from the Actions tab.

=== "Via Terraform"

    ```bash
    cd lablink-infrastructure
    terraform destroy -var="resource_suffix=test"
    ```

See [Deployment](deployment.md#destroying-a-deployment) for details.

### Review Costs

Check [Cost Estimation](cost-estimation.md) for guidance on reviewing your AWS bill and optimizing costs for future workshops.

## Related

- [API Endpoints](api-endpoints.md#admin-api-endpoints) for programmatic access to admin features
- [Configuration](configuration.md) for admin password and app settings
- [Security & Access](security.md) for authentication details
- [Troubleshooting](troubleshooting.md) for common issues

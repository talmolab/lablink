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
| **User Email** | Email of the participant assigned to the VM |
| **In Use** | Whether the VM is currently claimed by a participant |
| **VM Status** | Overall VM health status (running, initializing, stopped) |
| **GPU Health Status** | GPU availability and CUDA status |
| **Total Startup Duration** | How long the VM took to become ready |
| **Logs** | Link to view startup and runtime logs for the VM |
| **Access** | Per-VM actions (open the desktop, reboot, destroy) |

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
3. The allocator assigns them a VM and drops them straight into its desktop
4. The desktop opens in the browser tab with your software pre-installed

No installation, no setup -- participants only need a browser.

## During the Workshop

### Monitor the Dashboard

Keep the admin panel open to track participant activity:

![Admin panel](assets/images/admin-panel.png)

- **VM Status** column shows if VMs are running normally
- **GPU Health Status** confirms GPU availability for compute workloads
- **In Use** shows which VMs have been claimed
- **User Email** shows who is using each VM

### Adding More VMs

If more participants arrive than expected:

1. Click **"Create VMs"** in the admin panel
2. Enter the additional number needed
3. Click **"Launch VMs"**

New VMs are created without affecting existing running VMs. They'll be ready in about 5 minutes.

### Handling Issues

- **VM shows "error"**: The auto-reboot service will attempt to recover it automatically (up to 3 times). Check the logs link for details.
- **Participant can't connect**: Verify their VM shows "running" status and that they were assigned one. Try having them reload the allocator page to get a fresh session.
- **All VMs assigned**: Create additional VMs as described above.

## End of Workshop

### Destroy VMs

!!! warning "Participant files are not recoverable"
    LabLink does not collect work off the VMs. Tell participants to download
    anything they want to keep before the session ends -- destroying a VM
    destroys its disk.

Tear down all VMs:

1. Click **"Delete VMs"** in the admin panel
2. Click **"Run terraform destroy"** and confirm

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

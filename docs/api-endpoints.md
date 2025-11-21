# API Endpoints

This document outlines the API endpoints provided by the LabLink Allocator service.

## Public API Endpoints

These endpoints are designed for interaction with client VMs and end-users without requiring admin authentication.

### Request a VM

Assigns an available VM to a user.

- **Endpoint:** `POST /api/request_vm`
- **Description:** Submits a user's email and a Chrome Remote Desktop (CRD) command to be assigned to an available VM. If a VM is available, it is assigned to the user, and the user is shown a success page with connection details.
- **Authentication:** None
- **Request Body:** `application/x-www-form-urlencoded`
  - `email` (string, required): The user's email address.
  - `crd_command` (string, required): The CRD command for the session.
- **Success Response:**
  - **Code:** `200 OK`
  - **Content:** An HTML page (`success.html`) displaying the assigned VM's hostname and PIN.
- **Error Response:**
  - **Code:** `200 OK`
  - **Content:** An HTML page (`index.html`) with an error message displayed if no VMs are available, if required fields are missing, or if an invalid CRD command is provided.

### VM Startup Registration

Used by a client VM to register itself with the allocator upon startup and to listen for an assignment.

- **Endpoint:** `POST /vm_startup`
- **Description:** A client VM calls this endpoint after it boots up. It sends its hostname and then listens for a PostgreSQL notification that contains the assigned `CrdCommand` and `Pin`. This is a long-polling request.
- **Authentication:** None
- **Request Body:** `application/json`
  ```json
  {
    "hostname": "lablink-vm-prod-1"
  }
  ```
- **Success Response:**
  - **Code:** `200 OK`
  - **Content:**
    ```json
    {
      "status": "success",
      "pin": "123456",
      "command": "crd --code=..."
    }
    ```
- **Error Response:**
  - **Code:** `400 Bad Request` if `hostname` is not provided.
  - **Code:** `404 Not Found` if the VM with the given `hostname` is not found in the database.

### Get Unassigned VM Count

Retrieves the number of available (unassigned) VMs.

- **Endpoint:** `GET /api/unassigned_vms_count`
- **Description:** Returns the current count of VMs that are running and not yet assigned to a user.
- **Authentication:** None
- **Request Body:** None
- **Success Response:**
  - **Code:** `200 OK`
  - **Content:**
    ```json
    {
      "count": 5
    }
    ```

### Update VM In-Use Status

Updates the "in-use" status of a VM.

- **Endpoint:** `POST /api/update_inuse_status`
- **Description:** Called by the client VM to indicate whether a user is actively using it.
- **Authentication:** None
- **Request Body:** `application/json`
  ```json
  {
    "hostname": "lablink-vm-prod-1",
    "status": true
  }
  ```
- **Success Response:**
  - **Code:** `200 OK`
  - **Content:**
    ```json
    {
      "message": "In-use status updated successfully."
    }
    ```
- **Error Response:**
  - **Code:** `400 Bad Request` if `hostname` or `status` is missing.
  - **Code:** `500 Internal Server Error` on failure.

### Update GPU Health

Updates the GPU health status of a VM.

- **Endpoint:** `POST /api/gpu_health`
- **Description:** Called by the client VM to report its GPU health status.
- **Authentication:** None
- **Request Body:** `application/json`
  ```json
  {
    "hostname": "lablink-vm-prod-1",
    "gpu_status": "healthy"
  }
  ```
- **Success Response:**
  - **Code:** `200 OK`
  - **Content:**
    ```json
    {
      "message": "GPU health status updated successfully."
    }
    ```
- **Error Response:**
  - **Code:** `400 Bad Request` if `hostname` or `gpu_status` is missing.
  - **Code:** `500 Internal Server Error` on failure.

### Update VM Status

Updates the overall status of a VM (e.g., `initializing`, `running`, `error`).

- **Endpoint:** `POST /api/vm-status`
- **Description:** Called by the client VM during its startup sequence to report its current status.
- **Authentication:** None
- **Request Body:** `application/json`
  ```json
  {
    "hostname": "lablink-vm-prod-1",
    "status": "running"
  }
  ```
- **Success Response:**
  - **Code:** `200 OK`
  - **Content:**
    ```json
    {
      "message": "VM status updated successfully."
    }
    ```
- **Error Response:**
  - **Code:** `400 Bad Request` if `hostname` or `status` is missing.
  - **Code:** `500 Internal Server Error` on failure.

### Receive VM Metrics

Receives and stores startup metrics from a VM.

- **Endpoint:** `POST /api/vm-metrics/<hostname>`
- **Description:** Called by the client VM's `user_data.sh` script to post timing metrics for `cloud-init` and container startup.
- **Authentication:** None
- **URL Parameters:**
    - `hostname` (string, required): The hostname of the VM reporting metrics.
- **Request Body:** `application/json`
  ```json
  {
      "cloud_init_start": 1678886400,
      "cloud_init_end": 1678886460,
      "cloud_init_duration_seconds": 60
  }
  ```
- **Success Response:**
  - **Code:** `200 OK`
  - **Content:**
    ```json
    {
      "message": "VM metrics posted successfully."
    }
    ```
- **Error Response:**
  - **Code:** `404 Not Found` if the VM does not exist.
  - **Code:** `500 Internal Server Error` on failure.

### Receive VM Logs

Receives and stores logs pushed from a VM.

- **Endpoint:** `POST /api/vm-logs`
- **Description:** Called by the CloudWatch agent on the client VM (via a Lambda subscription) to push `cloud-init` logs to the allocator.
- **Authentication:** None
- **Request Body:** `application/json`
  ```json
  {
    "log_group": "/aws/ec2/lablink",
    "log_stream": "lablink-vm-prod-1",
    "messages": [
      "log line 1",
      "log line 2"
    ]
  }
  ```
- **Success Response:**
  - **Code:** `200 OK`
  - **Content:**
    ```json
    {
      "message": "VM logs posted successfully."
    }
    ```
- **Error Response:**
  - **Code:** `400 Bad Request` if required fields are missing.
  - **Code:** `404 Not Found` if the VM does not exist.
  - **Code:** `500 Internal Server Error` on failure.


## Admin API Endpoints

These endpoints require HTTP Basic Authentication and are intended for administrators to manage the VM pool.

### Launch VMs

Launches a specified number of new client VMs using Terraform.

- **Endpoint:** `POST /api/launch`
- **Description:** Takes a number of VMs to create, generates a Terraform variables file, and runs `terraform apply` to provision the new instances.
- **Authentication:** HTTP Basic Auth
- **Request Body:** `application/x-www-form-urlencoded`
  - `num_vms` (integer, required): The number of new VMs to launch.
- **Success Response:**
  - **Code:** `200 OK`
  - **Content:** An HTML page (`dashboard.html`) displaying the Terraform output and a real-time status monitor for the VMs.
- **Error Response:**
  - **Code:** `200 OK`
  - **Content:** An HTML page (`dashboard.html`) displaying the Terraform error output.

### Destroy All VMs

Destroys all client VMs and clears the database.

- **Endpoint:** `POST /destroy`
- **Description:** Runs `terraform destroy` to terminate all EC2 instances and associated resources created by LabLink. It also clears all records from the `vms` table in the database. **This is a destructive action.**
- **Authentication:** HTTP Basic Auth
- **Request Body:** None
- **Success Response:**
  - **Code:** `200 OK`
  - **Content:** An HTML page (`delete-dashboard.html`) displaying the Terraform output.
- **Error Response:**
  - **Code:** `200 OK`
  - **Content:** An HTML page (`delete-dashboard.html`) displaying the Terraform error output.

### Download All User Data

Downloads all user-generated data from all VMs.

- **Endpoint:** `GET /api/scp-client`
- **Description:** Connects to each running VM via SSH, finds all files matching the configured `extension`, copies them to a temporary directory on the allocator, zips them, and provides the zip file for download.
- **Authentication:** HTTP Basic Auth
- **Request Body:** None
- **Success Response:**
  - **Code:** `200 OK`
  - **Content-Type:** `application/zip`
  - **Content:** A zip file containing the data from all VMs.
- **Error Response:**
  - **Code:** `404 Not Found` if no VMs or no files are found.
  - **Code:** `500 Internal Server Error` if an error occurs during the SSH/SCP process.

### Get Status of All VMs

Retrieves the status of all VMs in the database.

- **Endpoint:** `GET /api/vm-status`
- **Description:** Returns a JSON object mapping each VM hostname to its current status. Used by the admin dashboard.
- **Authentication:** None (but intended for admin dashboard)
- **Request Body:** None
- **Success Response:**
  - **Code:** `200 OK`
  - **Content:**
    ```json
    {
      "lablink-vm-prod-1": "running",
      "lablink-vm-prod-2": "initializing"
    }
    ```
- **Error Response:**
  - **Code:** `404 Not Found` if no VMs are found in the database.
  - **Code:** `500 Internal Server Error` on failure.

### Get Status of a Specific VM

Retrieves the status of a single VM by its hostname.

- **Endpoint:** `GET /api/vm-status/<hostname>`
- **Description:** Returns the status of a specific VM.
- **Authentication:** None (but intended for admin dashboard)
- **URL Parameters:**
    - `hostname` (string, required): The hostname of the VM.
- **Request Body:** None
- **Success Response:**
  - **Code:** `200 OK`
  - **Content:**
    ```json
    {
      "hostname": "lablink-vm-prod-1",
      "status": "running"
    }
    ```
- **Error Response:**
  - **Code:** `404 Not Found` if the VM is not found.
  - **Code:** `500 Internal Server Error` on failure.

### Get Logs for a Specific VM

Retrieves the `cloud-init` logs for a single VM by its hostname.

- **Endpoint:** `GET /api/vm-logs/<hostname>`
- **Description:** Returns the stored logs for a specific VM. Used by the admin log viewer page.
- **Authentication:** HTTP Basic Auth (via the `/admin/logs/<hostname>` page)
- **URL Parameters:**
    - `hostname` (string, required): The hostname of the VM.
- **Request Body:** None
- **Success Response:**
  - **Code:** `200 OK`
  - **Content:**
    ```json
    {
      "hostname": "lablink-vm-prod-1",
      "logs": "Starting cloud-init...\n..."
    }
    ```
- **Error Response:**
  - **Code:** `404 Not Found` if the VM is not found.
  - **Code:** `503 Service Unavailable` if the logs are not yet available because the CloudWatch agent is still being installed.
  - **Code:** `500 Internal Server Error` on failure.

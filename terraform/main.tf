locals {
  num_instances = 10
  project       = var.project_id
  service_name  = "cosyne-service"
  database_name = "test-database-users"
}

# Creates a new instance
# resource "google_compute_instance" "test_instance" {
#   count          = local.num_instances
#   name           = "test-instance-${count.index}"
#   machine_type   = "e2-medium"
#   zone           = "us-west1-b"
#   can_ip_forward = false


#   boot_disk {
#     initialize_params {
#       image = "linux-pilot-sleap-gui-crd-pubsub-database-inuse-5"
#     }
#   }

#   network_interface {
#     network = "default"
#     access_config {}
#   }

#   # for each instance, create a startup script
#   metadata_startup_script = file("${path.module}/start_up.sh")

#   service_account {
#     scopes = ["https://www.googleapis.com/auth/spanner.data", "https://www.googleapis.com/auth/devstorage.read_only", "https://www.googleapis.com/auth/logging.write", "https://www.googleapis.com/auth/monitoring.write", "https://www.googleapis.com/auth/trace.append", "https://www.googleapis.com/auth/service.management.readonly", "https://www.googleapis.com/auth/servicecontrol"]
#   }
# }

# resource "google_pubsub_topic" "main" {
#   name = var.instance_name

# }

# Create Spanner Database in the specific instance
resource "google_spanner_database" "default" {
  name     = local.database_name
  instance = "vmassign-dev"
  ddl = [
    "CREATE TABLE Users (Hostname STRING(1024) NOT NULL, Pin STRING(1024), CrdCmd STRING(1024), UserEmail STRING(1024), inUse BOOL,) PRIMARY KEY (Hostname)"
  ]
  deletion_protection = false
}

resource "google_cloud_run_v2_service" "deployment" {
  name                = local.service_name
  location            = "us-central1"
  project             = var.project_id
  deletion_protection = false
  template {
    containers {
      image = "gcr.io/${var.project_id}/cosyne:latest"
    }
  }
}

#   traffic {
#     percent         = 100
#     latest_revision = true
#   }
# }

# data "google_iam_policy" "noauth" {
#   binding {
#     role = "roles/run.invoker"
#     members = [
#       "allUsers",
#     ]
#   }
# }

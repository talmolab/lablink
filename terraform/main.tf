variable "resource_suffic" {
  description = "Suffix to append to all resources"
  type        = string
  default     = "prod"
}

locals {
  project       = var.project_id
  service_name  = "cosyne-service"
  database_name = "test-database-users"
}

# TODO: Add resources for Terraform to manage

# TODO: Parameterize testing/development values

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
  traffic {
    percent = 100
  }
}

data "google_iam_policy" "noauth" {
  binding {
    role    = "roles/run.invoker"
    members = ["allUsers"]
  }
}

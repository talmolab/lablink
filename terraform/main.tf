locals {
  service_name  = "${var.resource_suffix}-cosyne-service"
  database_name = "users-${var.resource_suffix}"
  is_test       = var.resource_suffix == "test"
  is_staging    = var.resource_suffix == "staging"
  is_production = var.resource_suffix == "prod"
}

# Service Account Creation for spanner instance
resource "google_service_account" "spanner_admin_account" {
  account_id   = "spanner-admin"
  display_name = "Spanner Admin Service Account"
}

# Instance Creation
resource "google_spanner_instance" "database_instance" {
  name             = "vmassign-${var.resource_suffix}"
  display_name     = "Assign Instance ${var.resource_suffix}"
  config           = "regional-us-west1"
  processing_units = 1000
}


# Database Creation
resource "google_spanner_database" "default" {
  name     = "users"
  instance = google_spanner_instance.database_instance.name
  ddl = [
    "CREATE TABLE Users (Hostname STRING(1024) NOT NULL, Pin STRING(1024), CrdCmd STRING(1024), UserEmail STRING(1024), inUse BOOL,) PRIMARY KEY (Hostname)"
  ]
  deletion_protection = false
}

# Grant permissions to the new service account for Spanner
resource "google_spanner_database_iam_member" "spanner_permissions" {
  project  = var.project_id
  instance = google_spanner_instance.database_instance.name
  database = google_spanner_database.default.name
  role     = "roles/spanner.databaseAdmin"
  member   = "serviceAccount:${google_service_account.spanner_admin_account.email}"
}

# Service Account Creation for spanner instance
resource "google_service_account" "cloud_run_admin" {
  account_id   = "cloud-run-admin"
  display_name = "Cloud Run Admin Service Account"
}

# Deploy the web app
resource "google_cloud_run_service" "flask_service" {
  # count    = local.is_production || local.is_production || local.is_test ? 1 : 0
  name     = "flask-service"
  location = "us-central1"

  template {
    spec {
      containers {
        image = "us-central1-docker.pkg.dev/vmassign-dev/flask-app-repo/flask-app:latest"

        resources {
          limits = {
            memory = "256Mi"
            cpu    = "1"
          }
        }
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }
}

# Grant access to all users as an invoker
resource "google_cloud_run_service_iam_member" "invoker" {
  # count    = local.is_production ? 1 : 0
  service  = google_cloud_run_service.flask_service.name
  location = google_cloud_run_service.flask_service.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Grant permissions to the new service account for Spanner
resource "google_cloud_run_service_iam_member" "cloud_run_permission" {
  project = var.project_id
  service = google_cloud_run_service.flask_service.name
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.cloud_run_admin.email}"
}

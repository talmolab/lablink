locals {
  project       = var.project_id
  service_name  = "${var.resource_suffix}-cosyne-service"
  database_name = "users"
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

# Push an image to Google Container Registry
# NOTE: We can automate the process if we have the vmassign repo combined with this repo
# Google Artifact Registry
resource "google_artifact_registry_repository" "repo" {
  format        = "DOCKER"
  location      = "us-central1"
  repository_id = "flask-app-repo"
}

# resource "null_resource" "docker_build_and_push" {
#   provisioner "local-exec" {
#     command = <<EOT
#       gcloud auth configure-docker
#       docker build -t us-central1-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.name}/flask-app:latest ../
#       docker push us-central1-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.name}/flask-app:latest
#     EOT
#   }
# }

# Deployment using Cloud Run
resource "google_cloud_run_service" "flask_service" {
  name     = "flask-service"
  location = "us-central1"

  template {
    spec {
      containers {
        image = "gcr.io/${google_artifact_registry_repository.repo.name}/flask-app:latest"

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

resource "google_cloud_run_service_iam_member" "invoker" {
  service  = google_cloud_run_service.flask_service.name
  location = google_cloud_run_service.flask_service.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

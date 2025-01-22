# output "instance_id" {
#   description = "Instance ID"
#   value       = [for instance in google_compute_instance.test_instance : instance.id]
# }

# output "instance_name" {
#   description = "Instance Name"
#   value       = [for instance in google_compute_instance.test_instance : instance.name]
# }

output "service_url" {
  description = "Service URL"
  value       = google_cloud_run_v2_service.deployment.uri
}

output "vm_instance_ids" {
  description = "List of EC2 instance IDs created"
  value       = aws_instance.lablink_vm[*].id
}

output "vm_public_ips" {
  description = "List of public IPs assigned to the VMs"
  value       = aws_instance.lablink_vm[*].public_ip
}

output "lablink_private_key_pem" {
  description = "Private key used to access EC2 instances"
  value       = tls_private_key.lablink_key.private_key_pem
  sensitive   = true
}

output "vm_instance_names" {
  description = "List of names assigned to the EC2 instances"
  value       = [for instance in aws_instance.lablink_vm : instance.tags["Name"]]
}

output "startup_time_avg_seconds" {
  description = "Average startup time across all instances (seconds)"
  value       = local.avg_seconds
}
output "startup_time_max_seconds" {
  description = "Maximum startup time across all instances (seconds)"
  value       = local.max_seconds
}
output "startup_time_min_seconds" {
  description = "Minimum startup time across all instances (seconds)"
  value       = local.min_seconds
}

output "instance_startup_times" {
  description = "The Terraform apply time to cloud-init finished per instance"
  value = {
    for i in range(var.instance_count) :
    aws_instance.lablink_vm[i].tags.Name => {
      seconds = local.per_instance_seconds[i]
      formatted = local.per_instance_hms[i]
    }
  }
}
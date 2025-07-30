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

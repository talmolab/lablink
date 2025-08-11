variable "instance_count" {
  type    = number
  default = 1
}

variable "aws_access_key" {
  type        = string
  description = "AWS Access Key"
  sensitive   = true
}

variable "aws_secret_key" {
  type        = string
  description = "AWS Secret Key"
  sensitive   = true
}

variable "aws_session_token" {
  type        = string
  description = "AWS Session Token"
  sensitive   = true
}

variable "allocator_ip" {
  type        = string
  description = "IP address of the allocator server"
  sensitive   = true
}

variable "machine_type" {
  type        = string
  description = "Type of the machine to be created"
  default     = "t2.medium"
}

variable "image_name" {
  type        = string
  description = "VM Image Name to be used as client base image"
}

variable "repository" {
  type        = string
  description = "GitHub repository URL for the Data Repository"
}

variable "client_ami_id" {
  type        = string
  description = "AMI ID for the client VM"
}

variable "resource_suffix" {
  type        = string
  default     = "client"
  description = "Suffix to ensure uniqueness"
}

variable "subject_software" {
  type        = string
  default     = "sleap"
  description = "Software subject for the client VM"
}

variable "gpu_support" {
  type        = bool
  description = "Whether the instance machine type supports GPU"
}

variable "cloud_init_output_log_group" {
  type        = string
  description = "CloudWatch Log Group for client VM logs"
}

variable "region" {
  type        = string
  description = "AWS region where resources will be created"
}

variable "ssh_user" {
  type        = string
  description = "SSH user for the EC2 instance"
  default     = "ubuntu"
}

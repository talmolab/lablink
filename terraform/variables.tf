variable "instance_name" {
  description = "Name of the instance"
  type        = string
  default     = "web-server"
}

variable "project_id" {
  description = "Target Project ID"
  type        = string
  default     = "vmassign-dev"
}

variable "resource_suffix" {
  description = "Suffix to append to all resources"
  type        = string
  default     = "prod"
}

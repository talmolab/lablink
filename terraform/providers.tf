terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "6.5.0"
    }
  }
}

provider "google" {
  project     = "vmassign-dev"
  region      = "us-west1"
  credentials = "./vmassign-dev-2818ad83c3ff.json"
}

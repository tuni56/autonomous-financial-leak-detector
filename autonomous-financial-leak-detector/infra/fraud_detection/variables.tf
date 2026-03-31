variable "aws_region" {
  default = "us-east-2"
}

variable "alert_email" {
  description = "Email address for cost and operational alerts"
  type        = string
}

locals {
  tags = {
    Project     = "AFLD-Fraud"
    Owner       = "Rocio-Distinguished"
    Environment = "Staging-Demo"
  }
}

# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

variable "alias" {
  description = "KMS alias without the 'alias/' prefix (e.g. 'my-product')."
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9/_-]+$", var.alias)) && !startswith(var.alias, "alias/") && !startswith(var.alias, "aws/")
    error_message = "alias must not start with 'alias/' or 'aws/' and may only contain [A-Za-z0-9/_-]."
  }
}

variable "description" {
  description = "Human description for the KMS key."
  type        = string
  default     = "Shared platform KMS CMK"
}

variable "key_admins" {
  description = "IAM principal ARNs allowed to administer the key (rotate, delete, tag)."
  type        = list(string)
  default     = []
}

variable "key_users" {
  description = "IAM principal ARNs allowed to use the key (encrypt, decrypt, generate data keys, grants for AWS resources)."
  type        = list(string)
  default     = []
}

variable "enable_rotation" {
  description = "Enable automatic key rotation (annual)."
  type        = bool
  default     = true
}

variable "deletion_window_days" {
  description = "Waiting period in days between ScheduleKeyDeletion and actual deletion (7-30)."
  type        = number
  default     = 30

  validation {
    condition     = var.deletion_window_days >= 7 && var.deletion_window_days <= 30
    error_message = "deletion_window_days must be between 7 and 30."
  }
}

variable "tags" {
  description = "Tags to apply to the KMS key."
  type        = map(string)
  default     = {}
}

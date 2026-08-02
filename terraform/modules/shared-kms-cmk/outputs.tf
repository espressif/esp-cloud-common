# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

output "key_id" {
  description = "KMS key ID."
  value       = aws_kms_key.this.key_id
}

output "key_arn" {
  description = "KMS key ARN."
  value       = aws_kms_key.this.arn
}

output "alias_name" {
  description = "Full alias including 'alias/' prefix."
  value       = aws_kms_alias.this.name
}

output "alias_arn" {
  description = "KMS alias ARN."
  value       = aws_kms_alias.this.arn
}

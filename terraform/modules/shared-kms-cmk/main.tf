# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

terraform {
  required_version = ">= 1.10.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.100, < 6.0"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_root_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"

  root_statement = {
    sid       = "EnableIAMUserPermissions"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]
    principals = {
      type        = "AWS"
      identifiers = [local.account_root_arn]
    }
    condition = null
  }

  admin_statement = {
    sid    = "AllowKeyAdministration"
    effect = "Allow"
    actions = [
      "kms:Create*", "kms:Describe*", "kms:Enable*", "kms:List*",
      "kms:Put*", "kms:Update*", "kms:Revoke*", "kms:Disable*",
      "kms:Get*", "kms:Delete*", "kms:TagResource", "kms:UntagResource",
      "kms:ScheduleKeyDeletion", "kms:CancelKeyDeletion",
    ]
    resources = ["*"]
    principals = {
      type        = "AWS"
      identifiers = var.key_admins
    }
    condition = null
  }

  use_statement = {
    sid    = "AllowKeyUse"
    effect = "Allow"
    actions = [
      "kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*",
      "kms:GenerateDataKey*", "kms:DescribeKey",
    ]
    resources = ["*"]
    principals = {
      type        = "AWS"
      identifiers = var.key_users
    }
    condition = null
  }

  grant_statement = {
    sid    = "AllowAttachmentOfPersistentResources"
    effect = "Allow"
    actions = [
      "kms:CreateGrant", "kms:ListGrants", "kms:RevokeGrant",
    ]
    resources = ["*"]
    principals = {
      type        = "AWS"
      identifiers = var.key_users
    }
    condition = {
      test     = "Bool"
      variable = "kms:GrantIsForAWSResource"
      values   = ["true"]
    }
  }

  statements_all = [
    local.root_statement,
    local.admin_statement,
    local.use_statement,
    local.grant_statement,
  ]

  # Drop admin/user statements when their principal lists are empty.
  statements_include = [
    true,
    length(var.key_admins) > 0,
    length(var.key_users) > 0,
    length(var.key_users) > 0,
  ]

  statements = [
    for idx, stmt in local.statements_all :
    stmt if local.statements_include[idx]
  ]
}

data "aws_iam_policy_document" "key" {
  dynamic "statement" {
    for_each = local.statements
    content {
      sid       = statement.value.sid
      effect    = statement.value.effect
      actions   = statement.value.actions
      resources = statement.value.resources

      principals {
        type        = statement.value.principals.type
        identifiers = statement.value.principals.identifiers
      }

      dynamic "condition" {
        for_each = statement.value.condition == null ? [] : [statement.value.condition]
        content {
          test     = condition.value.test
          variable = condition.value.variable
          values   = condition.value.values
        }
      }
    }
  }
}

resource "aws_kms_key" "this" {
  description             = var.description
  enable_key_rotation     = var.enable_rotation
  deletion_window_in_days = var.deletion_window_days
  policy                  = data.aws_iam_policy_document.key.json
  tags                    = var.tags
}

resource "aws_kms_alias" "this" {
  name          = "alias/${var.alias}"
  target_key_id = aws_kms_key.this.key_id
}

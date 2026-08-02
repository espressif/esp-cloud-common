# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Path-independent CFN logical IDs.

CDK derives a construct's CloudFormation logical ID from its construct
*path*. Reparenting a construct (moving it under a different scope or
renaming an ancestor) changes the path and therefore the logical ID,
which CFN treats as a replace — destructive for stateful resources
(DynamoDB tables, S3 buckets, IAM role names that are referenced
elsewhere) and disruptive for everything else.

``stable_logical_id(resource_type, name)`` produces a deterministic,
CFN-safe (alphanumeric, PascalCase) logical ID that depends only on the
two inputs. Override the auto-generated logical ID on the L1
(``construct.node.default_child.override_logical_id(...)`` for L2s, or
``cfn_resource.override_logical_id(...)`` for L1s) so future refactors
that move the construct don't replace the resource.

Example:
    stable_logical_id("DDBTable", "my-app-users") → "DDBTableMyAppUsers"
    stable_logical_id("IAMRole", "admin_files_lambda_role")
                                                  → "IAMRoleAdminFilesLambdaRole"
"""

import re


def stable_logical_id(resource_type: str, name: str) -> str:
    segments = re.split(r"[^a-zA-Z0-9]+", name)
    pascal_name = "".join(seg[:1].upper() + seg[1:] for seg in segments if seg)
    return f"{resource_type}{pascal_name}"

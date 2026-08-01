# shared-kms-cmk

Creates a single customer-managed KMS key (CMK) with an alias, automatic key rotation, and admin/user principal bindings. Use this when you want one shared KMS key for a whole product and distribute access via IAM rather than per-resource keys.

## Example

```hcl
module "platform_cmk" {
  source = "git::<git_url>//terraform/modules/shared-kms-cmk?ref=v0.1.0"

  alias       = "<product_name>"
  description = "<product_name> shared platform key"

  key_admins = []   # root has full control; add engineer roles here if needed
  key_users  = [
    aws_iam_role.edge_lambda.arn,
    aws_iam_role.control_plane_lambda.arn,
  ]

  tags = {
    Project = "<product_name>"
  }
}
```

During active co-development of a consumer + module, the `source` may be a local relative path. Switch to a pinned git ref before merging.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `alias` | string | — | Alias without `alias/` prefix. Reserved namespaces (`aws/`) are rejected. |
| `description` | string | `"Shared platform KMS CMK"` | Key description. |
| `key_admins` | list(string) | `[]` | IAM ARNs permitted to administer the key. |
| `key_users` | list(string) | `[]` | IAM ARNs permitted to encrypt/decrypt/generate-data-key and create grants for AWS resources. |
| `enable_rotation` | bool | `true` | Annual automatic rotation. |
| `deletion_window_days` | number | `30` | 7–30. |
| `tags` | map(string) | `{}` | Key tags. |

## Outputs

| Name | Description |
|---|---|
| `key_id` | Key ID. |
| `key_arn` | Key ARN. |
| `alias_name` | Full alias (`alias/...`). |
| `alias_arn` | Alias ARN. |

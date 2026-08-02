# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for IAM role protection.

These exist because deleting an
``AWSReservedSSO_AWSAdministratorAccess_*`` role at path
``/aws-reserved/sso.amazonaws.com/<region>/`` locks the operator
out of the account until an Identity Center admin re-provisions the
permission set assignment.

The cleanup must skip:
  - Path ``/aws-service-role/...`` — service-linked roles.
  - Path ``/aws-reserved/...`` — Identity Center provisioning roles.
  - Name ``OrganizationAccountAccessRole`` — Organizations cross-account default.
  - Name prefix ``AWSReservedSSO_`` — Identity Center belt-and-suspenders.
  - Name prefix ``aws-controltower-`` — Control Tower.
  - Name prefix ``stacksets-exec-`` — CloudFormation StackSets.

If you broaden this skip list, add a test. Don't shrink it without thinking
very hard.
"""

import pytest

from services.iam import _role_is_protected, _saml_provider_is_protected


@pytest.mark.parametrize('role', [
    # SSO admin role for an account — deleting this locks the operator out.
    {
        'RoleName': 'AWSReservedSSO_AWSAdministratorAccess_0123456789abcdef',
        'Path': '/aws-reserved/sso.amazonaws.com/us-east-1/',
    },
    # Other reserved-path SSO roles.
    {
        'RoleName': 'AWSReservedSSO_DeveloperAccess_abc123',
        'Path': '/aws-reserved/sso.amazonaws.com/eu-west-1/',
    },
    # Service-linked roles — original protection.
    {
        'RoleName': 'AWSServiceRoleForRDS',
        'Path': '/aws-service-role/rds.amazonaws.com/',
    },
    {
        'RoleName': 'AWSServiceRoleForLambda',
        'Path': '/aws-service-role/lambda.amazonaws.com/',
    },
    # Org cross-account default.
    {
        'RoleName': 'OrganizationAccountAccessRole',
        'Path': '/',
    },
    # Control Tower roles.
    {
        'RoleName': 'aws-controltower-AdministratorExecutionRole',
        'Path': '/',
    },
    # StackSets execution role.
    {
        'RoleName': 'stacksets-exec-1234567890abcdef',
        'Path': '/',
    },
])
def test_protected_roles_are_skipped(role):
    assert _role_is_protected(role), \
        f'Role {role["RoleName"]} (path {role["Path"]}) must be protected'


@pytest.mark.parametrize('role', [
    # Plain customer roles created by CloudFormation, terraform, etc.
    {
        'RoleName': 'my-stack-ServiceCoreLambdaRole-AbCdEf',
        'Path': '/',
    },
    {
        'RoleName': 'my-app-task-role',
        'Path': '/',
    },
    # Customer role under a custom path.
    {
        'RoleName': 'pipeline-deploy-role',
        'Path': '/ci/',
    },
    # Adversarial: a role named to look like an SSO role but at a normal path.
    # We protect by both path AND name prefix, so this is still protected.
    # (Kept here so anyone reading the negative cases sees it explicitly.)
])
def test_normal_customer_roles_are_not_skipped(role):
    assert not _role_is_protected(role), \
        f'Role {role["RoleName"]} (path {role["Path"]}) should be deletable'


def test_role_name_lookalike_at_normal_path_is_still_protected():
    """If someone names a customer role exactly ``AWSReservedSSO_foo`` at /,
    we still skip it. Slight false-positive risk, but the cost of deleting
    a real SSO role is much worse than skipping one customer role with a
    confusing name."""
    role = {
        'RoleName': 'AWSReservedSSO_NotARealSSORole',
        'Path': '/',
    }
    assert _role_is_protected(role)


# --- SAML provider protection -------------------------------------------

@pytest.mark.parametrize('arn', [
    # Identity Center SAML provider — deleting this breaks SSO sign-in.
    'arn:aws:iam::123456789012:saml-provider/AWSSSO_0123456789abcdef_DO_NOT_DELETE',
    # Variations of the same shape.
    'arn:aws:iam::123456789012:saml-provider/AWSSSO_abc',
    'arn:aws:iam::123456789012:saml-provider/Customer_DO_NOT_DELETE',
    'arn:aws:iam::123456789012:saml-provider/AWSSSO_PreviewProvider',
])
def test_protected_saml_providers_are_skipped(arn):
    assert _saml_provider_is_protected(arn), \
        f'SAML provider {arn} must be protected'


@pytest.mark.parametrize('arn', [
    # Legitimate customer SAML providers used for, e.g., Okta/AzureAD federation.
    'arn:aws:iam::123456789012:saml-provider/Okta',
    'arn:aws:iam::123456789012:saml-provider/CustomFederation',
    'arn:aws:iam::123456789012:saml-provider/MyCorp',
])
def test_normal_saml_providers_are_not_skipped(arn):
    assert not _saml_provider_is_protected(arn), \
        f'SAML provider {arn} should be deletable'

# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""IAM cleanup — all customer-managed identities and credentials.

Covers: users (with their access keys, login profile, MFA, attached/inline
policies, group memberships, signing certs, SSH keys, service-specific
credentials), groups, customer-managed policies (with all versions),
roles, instance profiles, OIDC + SAML identity providers, server
certificates.

ALWAYS SKIPPED — these are infrastructure roles whose deletion locks you
out of the account or breaks org-level controls:

  - Path ``/aws-service-role/...`` — service-linked roles (cannot be
    deleted via IAM API anyway).
  - Path ``/aws-reserved/...`` — IAM Identity Center provisioning roles
    (``AWSReservedSSO_<permission-set>_<hash>``). Deleting these means the
    permission set can no longer be assumed in the account, locking out
    SSO users until the assignment is re-provisioned from the Identity
    Center management account.
  - Name ``OrganizationAccountAccessRole`` — default org cross-account
    admin role.
  - Name ``aws-controltower-*`` and ``stacksets-exec-*`` — Control Tower
    and CloudFormation StackSets execution roles.

Deleting the ``AWSReservedSSO_AWSAdministratorAccess_*`` role locks the
operator out of the account entirely. Don't relax these skips.
"""

import click
from botocore.exceptions import ClientError

from .base import ServiceCleanup


_PROTECTED_ROLE_PATH_PREFIXES = (
    '/aws-service-role/',
    '/aws-reserved/',
)

_PROTECTED_ROLE_NAME_PREFIXES = (
    'AWSReservedSSO_',
    'aws-controltower-',
    'stacksets-exec-',
)

_PROTECTED_ROLE_NAMES = {
    'OrganizationAccountAccessRole',
}

# SAML providers that back AWS-managed federation. Deleting an AWSSSO_*
# provider (the SAML federation trust IAM Identity Center installs in each
# member account) breaks SSO login the same way deleting AWSReservedSSO_*
# roles does. AWS marks these with a ``_DO_NOT_DELETE`` suffix as a hint.
_PROTECTED_SAML_PROVIDER_NAME_SUBSTRINGS = (
    'AWSSSO',
    'DO_NOT_DELETE',
)


def _role_is_protected(role):
    name = role.get('RoleName', '')
    path = role.get('Path', '/')
    if path.startswith(_PROTECTED_ROLE_PATH_PREFIXES):
        return True
    if name.startswith(_PROTECTED_ROLE_NAME_PREFIXES):
        return True
    if name in _PROTECTED_ROLE_NAMES:
        return True
    return False


def _saml_provider_is_protected(arn):
    # SAML provider ARNs look like
    # ``arn:aws:iam::<account>:saml-provider/<name>`` — match the trailing
    # name component case-insensitively against known protected substrings.
    name = arn.rsplit('/', 1)[-1]
    return any(s in name for s in _PROTECTED_SAML_PROVIDER_NAME_SUBSTRINGS)


class IAMCleanup(ServiceCleanup):
    name = 'iam'
    boto_client = 'iam'
    cli_options = [
        click.option(
            '--iam-role-include-prefix', 'iam_role_include_prefixes', multiple=True,
            help='Only process IAM roles whose name starts with one of these prefixes. '
                 'Repeatable. If unset, all customer-managed roles are processed.',
        ),
        click.option(
            '--iam-user-include-prefix', 'iam_user_include_prefixes', multiple=True,
            help='Only process IAM users whose name starts with one of these prefixes. '
                 'Repeatable. If unset, all users are processed.',
        ),
    ]

    def run(self):
        self._cleanup_users()
        self._cleanup_groups()
        self._cleanup_roles()
        self._cleanup_instance_profiles()
        self._cleanup_customer_policies()
        self._cleanup_oidc_providers()
        self._cleanup_saml_providers()
        self._cleanup_server_certificates()
        self.console.print("\n[bold green]IAM cleanup completed[/bold green]")

    # ---- users ----
    def _cleanup_users(self):
        include = tuple(self.options.get('iam_user_include_prefixes') or ())
        self.console.print("[bold cyan]Listing IAM users...[/bold cyan]")
        users = []
        for page in self.client.get_paginator('list_users').paginate():
            for user in page.get('Users', []):
                name = user.get('UserName')
                if include and not name.startswith(include):
                    continue
                users.append(user)
                self.console.print(f"Found user: {name}")

        for user in users:
            uname = user.get('UserName')
            try:
                self._scrub_user(uname)
                self.client.delete_user(UserName=uname)
                self.console.print(f"[green]✓ Deleted user: {uname}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting user {uname}: {e}[/red]")

    def _scrub_user(self, uname):
        # Access keys
        try:
            for k in self.client.list_access_keys(UserName=uname).get('AccessKeyMetadata', []):
                self.client.delete_access_key(UserName=uname, AccessKeyId=k['AccessKeyId'])
        except ClientError as e:
            self.console.print(f"[yellow]⚠ access keys for {uname}: {e}[/yellow]")

        # Login profile (console password)
        try:
            self.client.delete_login_profile(UserName=uname)
        except ClientError as e:
            if e.response['Error']['Code'] != 'NoSuchEntity':
                self.console.print(f"[yellow]⚠ login profile for {uname}: {e}[/yellow]")

        # MFA devices
        try:
            for mfa in self.client.list_mfa_devices(UserName=uname).get('MFADevices', []):
                self.client.deactivate_mfa_device(UserName=uname, SerialNumber=mfa['SerialNumber'])
                if mfa['SerialNumber'].startswith('arn:'):
                    self.client.delete_virtual_mfa_device(SerialNumber=mfa['SerialNumber'])
        except ClientError as e:
            self.console.print(f"[yellow]⚠ MFA for {uname}: {e}[/yellow]")

        # Signing certs
        try:
            for c in self.client.list_signing_certificates(UserName=uname).get('Certificates', []):
                self.client.delete_signing_certificate(UserName=uname, CertificateId=c['CertificateId'])
        except ClientError:
            pass

        # SSH public keys
        try:
            for k in self.client.list_ssh_public_keys(UserName=uname).get('SSHPublicKeys', []):
                self.client.delete_ssh_public_key(UserName=uname, SSHPublicKeyId=k['SSHPublicKeyId'])
        except ClientError:
            pass

        # Service-specific credentials
        try:
            for c in self.client.list_service_specific_credentials(UserName=uname).get('ServiceSpecificCredentials', []):
                self.client.delete_service_specific_credential(
                    UserName=uname, ServiceSpecificCredentialId=c['ServiceSpecificCredentialId'],
                )
        except ClientError:
            pass

        # Group memberships
        try:
            for g in self.client.list_groups_for_user(UserName=uname).get('Groups', []):
                self.client.remove_user_from_group(UserName=uname, GroupName=g['GroupName'])
        except ClientError as e:
            self.console.print(f"[yellow]⚠ group membership for {uname}: {e}[/yellow]")

        # Attached managed policies
        try:
            for p in self.client.list_attached_user_policies(UserName=uname).get('AttachedPolicies', []):
                self.client.detach_user_policy(UserName=uname, PolicyArn=p['PolicyArn'])
        except ClientError:
            pass

        # Inline policies
        try:
            for pname in self.client.list_user_policies(UserName=uname).get('PolicyNames', []):
                self.client.delete_user_policy(UserName=uname, PolicyName=pname)
        except ClientError:
            pass

    # ---- groups ----
    def _cleanup_groups(self):
        self.console.print("\n[bold cyan]Listing IAM groups...[/bold cyan]")
        groups = []
        for page in self.client.get_paginator('list_groups').paginate():
            for g in page.get('Groups', []):
                groups.append(g)
                self.console.print(f"Found group: {g.get('GroupName')}")

        for g in groups:
            gname = g.get('GroupName')
            try:
                # Detach managed policies
                for p in self.client.list_attached_group_policies(GroupName=gname).get('AttachedPolicies', []):
                    self.client.detach_group_policy(GroupName=gname, PolicyArn=p['PolicyArn'])
                # Delete inline policies
                for pname in self.client.list_group_policies(GroupName=gname).get('PolicyNames', []):
                    self.client.delete_group_policy(GroupName=gname, PolicyName=pname)
                # Remove remaining members (should be empty after _cleanup_users)
                for u in self.client.get_group(GroupName=gname).get('Users', []):
                    self.client.remove_user_from_group(GroupName=gname, UserName=u['UserName'])

                self.client.delete_group(GroupName=gname)
                self.console.print(f"[green]✓ Deleted group: {gname}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting group {gname}: {e}[/red]")

    # ---- roles ----
    def _cleanup_roles(self):
        include = tuple(self.options.get('iam_role_include_prefixes') or ())
        self.console.print("\n[bold cyan]Listing IAM roles...[/bold cyan]")
        roles = []
        for page in self.client.get_paginator('list_roles').paginate():
            for role in page.get('Roles', []):
                name = role.get('RoleName', '')
                if _role_is_protected(role):
                    continue
                if include and not name.startswith(include):
                    continue
                roles.append(role)
                self.console.print(f"Found role: {name}")

        for role in roles:
            rname = role.get('RoleName')
            try:
                # Detach managed policies
                for p in self.client.list_attached_role_policies(RoleName=rname).get('AttachedPolicies', []):
                    self.client.detach_role_policy(RoleName=rname, PolicyArn=p['PolicyArn'])
                # Delete inline policies
                for pname in self.client.list_role_policies(RoleName=rname).get('PolicyNames', []):
                    self.client.delete_role_policy(RoleName=rname, PolicyName=pname)
                # Remove from instance profiles
                for ip in self.client.list_instance_profiles_for_role(RoleName=rname).get('InstanceProfiles', []):
                    self.client.remove_role_from_instance_profile(
                        InstanceProfileName=ip['InstanceProfileName'], RoleName=rname,
                    )

                self.client.delete_role(RoleName=rname)
                self.console.print(f"[green]✓ Deleted role: {rname}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting role {rname}: {e}[/red]")

    # ---- instance profiles ----
    def _cleanup_instance_profiles(self):
        self.console.print("\n[bold cyan]Listing IAM instance profiles...[/bold cyan]")
        for page in self.client.get_paginator('list_instance_profiles').paginate():
            for ip in page.get('InstanceProfiles', []):
                name = ip.get('InstanceProfileName')
                try:
                    for role in ip.get('Roles', []):
                        self.client.remove_role_from_instance_profile(
                            InstanceProfileName=name, RoleName=role['RoleName'],
                        )
                    self.client.delete_instance_profile(InstanceProfileName=name)
                    self.console.print(f"[green]✓ Deleted instance profile: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting instance profile {name}: {e}[/red]")

    # ---- customer-managed policies ----
    def _cleanup_customer_policies(self):
        self.console.print("\n[bold cyan]Listing customer-managed IAM policies...[/bold cyan]")
        for page in self.client.get_paginator('list_policies').paginate(Scope='Local'):
            for policy in page.get('Policies', []):
                arn = policy.get('Arn')
                pname = policy.get('PolicyName')
                try:
                    # Must detach from all entities first
                    entities = self.client.list_entities_for_policy(PolicyArn=arn)
                    for u in entities.get('PolicyUsers', []):
                        self.client.detach_user_policy(UserName=u['UserName'], PolicyArn=arn)
                    for g in entities.get('PolicyGroups', []):
                        self.client.detach_group_policy(GroupName=g['GroupName'], PolicyArn=arn)
                    for r in entities.get('PolicyRoles', []):
                        self.client.detach_role_policy(RoleName=r['RoleName'], PolicyArn=arn)

                    # Delete non-default versions
                    for v in self.client.list_policy_versions(PolicyArn=arn).get('Versions', []):
                        if not v.get('IsDefaultVersion'):
                            self.client.delete_policy_version(PolicyArn=arn, VersionId=v['VersionId'])

                    self.client.delete_policy(PolicyArn=arn)
                    self.console.print(f"[green]✓ Deleted policy: {pname}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting policy {pname}: {e}[/red]")

    # ---- OIDC providers ----
    def _cleanup_oidc_providers(self):
        self.console.print("\n[bold cyan]Listing IAM OIDC providers...[/bold cyan]")
        try:
            for p in self.client.list_open_id_connect_providers().get('OpenIDConnectProviderList', []):
                arn = p['Arn']
                try:
                    self.client.delete_open_id_connect_provider(OpenIDConnectProviderArn=arn)
                    self.console.print(f"[green]✓ Deleted OIDC provider: {arn}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting OIDC provider {arn}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list OIDC providers: {e}[/yellow]")

    # ---- SAML providers ----
    def _cleanup_saml_providers(self):
        self.console.print("\n[bold cyan]Listing IAM SAML providers...[/bold cyan]")
        try:
            for p in self.client.list_saml_providers().get('SAMLProviderList', []):
                arn = p['Arn']
                if _saml_provider_is_protected(arn):
                    self.console.print(f"[yellow]Skipping protected SAML provider: {arn}[/yellow]")
                    continue
                try:
                    self.client.delete_saml_provider(SAMLProviderArn=arn)
                    self.console.print(f"[green]✓ Deleted SAML provider: {arn}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting SAML provider {arn}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list SAML providers: {e}[/yellow]")

    # ---- server certificates ----
    def _cleanup_server_certificates(self):
        self.console.print("\n[bold cyan]Listing IAM server certificates...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_server_certificates').paginate():
                for c in page.get('ServerCertificateMetadataList', []):
                    name = c.get('ServerCertificateName')
                    try:
                        self.client.delete_server_certificate(ServerCertificateName=name)
                        self.console.print(f"[green]✓ Deleted server cert: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting server cert {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list server certs: {e}[/yellow]")

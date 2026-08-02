# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""AWS Code* family cleanup.

Single module covering CodeBuild, CodePipeline, CodeCommit, CodeDeploy,
CodeArtifact. Each is a separate boto3 client.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup, _DryRunClient


class CodeSuiteCleanup(ServiceCleanup):
    name = 'codesuite'
    boto_client = 'codebuild'  # used for the base self.client
    cli_options = []

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        def _wrap(real, name):
            return _DryRunClient(real, name, console) if dry_run else real
        self.codepipeline = _wrap(session.client('codepipeline'), 'codepipeline')
        self.codecommit = _wrap(session.client('codecommit'), 'codecommit')
        self.codedeploy = _wrap(session.client('codedeploy'), 'codedeploy')
        self.codeartifact = _wrap(session.client('codeartifact'), 'codeartifact')

    def run(self):
        self._codebuild()
        self._codepipeline()
        self._codecommit()
        self._codedeploy()
        self._codeartifact()
        self.console.print("\n[bold green]CodeSuite cleanup completed[/bold green]")

    def _codebuild(self):
        self.console.print("[bold cyan]Listing CodeBuild projects...[/bold cyan]")
        try:
            names = []
            for page in self.client.get_paginator('list_projects').paginate():
                names.extend(page.get('projects', []))
            for i in range(0, len(names), 100):
                batch = names[i:i + 100]
                try:
                    self.client.batch_delete_builds  # ensure attr exists; we use individual deletes for projects
                except AttributeError:
                    pass
            for name in names:
                try:
                    self.client.delete_project(name=name)
                    self.console.print(f"[green]✓ Deleted CodeBuild project: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting CodeBuild project {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list CodeBuild projects: {e}[/yellow]")

        # Source credentials
        try:
            for cred in self.client.list_source_credentials().get('sourceCredentialsInfos', []):
                arn = cred.get('arn')
                try:
                    self.client.delete_source_credentials(arn=arn)
                    self.console.print(f"[green]✓ Deleted source credential: {arn}[/green]")
                except ClientError as e:
                    self.console.print(f"[yellow]⚠ Could not delete source credential: {e}[/yellow]")
        except ClientError:
            pass

    def _codepipeline(self):
        self.console.print("\n[bold cyan]Listing CodePipeline pipelines...[/bold cyan]")
        try:
            for page in self.codepipeline.get_paginator('list_pipelines').paginate():
                for p in page.get('pipelines', []):
                    name = p.get('name')
                    try:
                        self.codepipeline.delete_pipeline(name=name)
                        self.console.print(f"[green]✓ Deleted pipeline: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting pipeline {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list pipelines: {e}[/yellow]")

    def _codecommit(self):
        self.console.print("\n[bold cyan]Listing CodeCommit repositories...[/bold cyan]")
        try:
            for page in self.codecommit.get_paginator('list_repositories').paginate():
                for r in page.get('repositories', []):
                    name = r.get('repositoryName')
                    try:
                        self.codecommit.delete_repository(repositoryName=name)
                        self.console.print(f"[green]✓ Deleted CodeCommit repo: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting CodeCommit repo {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list CodeCommit repos: {e}[/yellow]")

    def _codedeploy(self):
        self.console.print("\n[bold cyan]Listing CodeDeploy applications...[/bold cyan]")
        try:
            for page in self.codedeploy.get_paginator('list_applications').paginate():
                for name in page.get('applications', []):
                    # Deployment groups under the app are deleted by deleting the app.
                    try:
                        self.codedeploy.delete_application(applicationName=name)
                        self.console.print(f"[green]✓ Deleted CodeDeploy application: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting CodeDeploy app {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list CodeDeploy apps: {e}[/yellow]")

        # Custom deployment configs (skip CodeDeployDefault.* — AWS-managed)
        try:
            for page in self.codedeploy.get_paginator('list_deployment_configs').paginate():
                for cfg in page.get('deploymentConfigsList', []):
                    if cfg.startswith('CodeDeployDefault.'):
                        continue
                    try:
                        self.codedeploy.delete_deployment_config(deploymentConfigName=cfg)
                        self.console.print(f"[green]✓ Deleted deployment config: {cfg}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting deployment config {cfg}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list deployment configs: {e}[/yellow]")

    def _codeartifact(self):
        self.console.print("\n[bold cyan]Listing CodeArtifact domains...[/bold cyan]")
        try:
            for page in self.codeartifact.get_paginator('list_domains').paginate():
                for d in page.get('domains', []):
                    domain = d.get('name')
                    owner = d.get('owner')
                    # Delete repos under the domain first
                    try:
                        for r_page in self.codeartifact.get_paginator('list_repositories_in_domain').paginate(
                            domain=domain, domainOwner=owner,
                        ):
                            for repo in r_page.get('repositories', []):
                                try:
                                    self.codeartifact.delete_repository(
                                        domain=domain, domainOwner=owner,
                                        repository=repo.get('name'),
                                    )
                                except ClientError as e:
                                    self.console.print(f"[yellow]⚠ Could not delete CodeArtifact repo: {e}[/yellow]")
                    except ClientError:
                        pass

                    try:
                        self.codeartifact.delete_domain(domain=domain, domainOwner=owner)
                        self.console.print(f"[green]✓ Deleted CodeArtifact domain: {domain}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting CodeArtifact domain {domain}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list CodeArtifact domains: {e}[/yellow]")

from botocore.exceptions import ClientError

from .base import ServiceCleanup, _DryRunClient


class ECRCleanup(ServiceCleanup):
    """ECR cleanup — private and public repositories.

    ECR Public uses a separate ``ecr-public`` API and only operates from
    us-east-1; the public client below pins that region regardless of the
    session region.
    """

    name = 'ecr'
    boto_client = 'ecr'
    cli_options = []

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        public_real = session.client('ecr-public', region_name='us-east-1')
        self.public = _DryRunClient(public_real, 'ecr-public', console) if dry_run else public_real

    def run(self):
        self._delete_private_repos()
        self._delete_public_repos()
        self.console.print("\n[bold green]ECR cleanup completed[/bold green]")

    def _delete_private_repos(self):
        self.console.print("[bold cyan]Listing ECR private repositories...[/bold cyan]")
        repos = []
        for page in self.client.get_paginator('describe_repositories').paginate():
            for repo in page.get('repositories', []):
                repos.append(repo)
                self.console.print(f"Found repo: {repo.get('repositoryName')}")

        for repo in repos:
            name = repo.get('repositoryName')
            try:
                self.client.delete_repository(repositoryName=name, force=True)
                self.console.print(f"[green]✓ Deleted private repo: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting private repo {name}: {e}[/red]")

    def _delete_public_repos(self):
        self.console.print("\n[bold cyan]Listing ECR public repositories...[/bold cyan]")
        try:
            for page in self.public.get_paginator('describe_repositories').paginate():
                for repo in page.get('repositories', []):
                    name = repo.get('repositoryName')
                    try:
                        self.public.delete_repository(repositoryName=name, force=True)
                        self.console.print(f"[green]✓ Deleted public repo: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting public repo {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list public repositories: {e}[/yellow]")

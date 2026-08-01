"""Bedrock cleanup — custom models, knowledge bases, agents, guardrails,
provisioned throughput, model invocation log configurations.

Bedrock has multiple boto3 clients: ``bedrock`` (control plane),
``bedrock-agent`` (agents/knowledge bases), ``bedrock-runtime``
(invocation — read-only). We touch the first two.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup, _DryRunClient


class BedrockCleanup(ServiceCleanup):
    name = 'bedrock'
    boto_client = 'bedrock'
    cli_options = []

    def __init__(self, session, console, dry_run=False, options=None):
        super().__init__(session, console, dry_run, options)
        agent_real = session.client('bedrock-agent')
        self.agent = _DryRunClient(agent_real, 'bedrock-agent', console) if dry_run else agent_real

    def run(self):
        self._delete_provisioned_throughput()
        self._delete_custom_models()
        self._delete_guardrails()
        self._delete_agents()
        self._delete_knowledge_bases()
        self.console.print("\n[bold green]Bedrock cleanup completed[/bold green]")

    def _delete_provisioned_throughput(self):
        self.console.print("[bold cyan]Listing Bedrock provisioned throughputs...[/bold cyan]")
        try:
            response = self.client.list_provisioned_model_throughputs()
            for pmt in response.get('provisionedModelSummaries', []):
                arn = pmt.get('provisionedModelArn')
                name = pmt.get('provisionedModelName')
                try:
                    self.client.delete_provisioned_model_throughput(provisionedModelId=arn)
                    self.console.print(f"[green]✓ Deleted provisioned throughput: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting provisioned throughput {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list provisioned throughputs: {e}[/yellow]")

    def _delete_custom_models(self):
        self.console.print("\n[bold cyan]Listing Bedrock custom models...[/bold cyan]")
        try:
            response = self.client.list_custom_models()
            for m in response.get('modelSummaries', []):
                arn = m.get('modelArn')
                name = m.get('modelName')
                try:
                    self.client.delete_custom_model(modelIdentifier=arn)
                    self.console.print(f"[green]✓ Deleted custom model: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting custom model {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list custom models: {e}[/yellow]")

    def _delete_guardrails(self):
        self.console.print("\n[bold cyan]Listing Bedrock guardrails...[/bold cyan]")
        try:
            response = self.client.list_guardrails()
            for g in response.get('guardrails', []):
                gid = g.get('id')
                name = g.get('name')
                try:
                    self.client.delete_guardrail(guardrailIdentifier=gid)
                    self.console.print(f"[green]✓ Deleted guardrail: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting guardrail {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list guardrails: {e}[/yellow]")

    def _delete_agents(self):
        self.console.print("\n[bold cyan]Listing Bedrock agents...[/bold cyan]")
        try:
            for page in self.agent.get_paginator('list_agents').paginate():
                for a in page.get('agentSummaries', []):
                    aid = a.get('agentId')
                    name = a.get('agentName')
                    try:
                        self.agent.delete_agent(agentId=aid, skipResourceInUseCheck=True)
                        self.console.print(f"[green]✓ Deleted agent: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting agent {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list agents: {e}[/yellow]")

    def _delete_knowledge_bases(self):
        self.console.print("\n[bold cyan]Listing Bedrock knowledge bases...[/bold cyan]")
        try:
            for page in self.agent.get_paginator('list_knowledge_bases').paginate():
                for kb in page.get('knowledgeBaseSummaries', []):
                    kid = kb.get('knowledgeBaseId')
                    name = kb.get('name')
                    try:
                        # Delete data sources first
                        try:
                            for ds_page in self.agent.get_paginator('list_data_sources').paginate(knowledgeBaseId=kid):
                                for ds in ds_page.get('dataSourceSummaries', []):
                                    self.agent.delete_data_source(
                                        knowledgeBaseId=kid, dataSourceId=ds['dataSourceId'],
                                    )
                        except ClientError:
                            pass
                        self.agent.delete_knowledge_base(knowledgeBaseId=kid)
                        self.console.print(f"[green]✓ Deleted knowledge base: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting knowledge base {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list knowledge bases: {e}[/yellow]")

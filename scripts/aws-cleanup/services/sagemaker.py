"""SageMaker cleanup.

Covers the most common cost-bearing resources:
  - Endpoints (most expensive — billable while InService).
  - Endpoint configs.
  - Models.
  - Notebook instances (stop → delete).
  - Pipelines.
  - Domains and user profiles (Studio).
  - Apps (within domains).
  - Feature groups.
  - Inference components.
  - Training/processing/transform jobs are NOT explicitly deleted —
    completed jobs are kept by AWS as immutable history; running ones
    are stopped.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup


class SageMakerCleanup(ServiceCleanup):
    name = 'sagemaker'
    boto_client = 'sagemaker'
    cli_options = []

    def run(self):
        self._stop_running_jobs()
        self._delete_endpoints()
        self._delete_inference_components()
        self._delete_endpoint_configs()
        self._delete_models()
        self._delete_pipelines()
        self._delete_feature_groups()
        self._delete_notebook_instances()
        self._delete_apps_and_domains()
        self.console.print("\n[bold green]SageMaker cleanup completed[/bold green]")

    def _stop_running_jobs(self):
        for job_kind, list_method, stop_method, status_field, name_field in [
            ('training', 'list_training_jobs', 'stop_training_job', 'TrainingJobStatus', 'TrainingJobName'),
            ('processing', 'list_processing_jobs', 'stop_processing_job', 'ProcessingJobStatus', 'ProcessingJobName'),
            ('transform', 'list_transform_jobs', 'stop_transform_job', 'TransformJobStatus', 'TransformJobName'),
        ]:
            self.console.print(f"\n[bold cyan]Stopping running {job_kind} jobs...[/bold cyan]")
            try:
                paginator = self.client.get_paginator(list_method)
                for page in paginator.paginate(StatusEquals='InProgress'):
                    summaries_key = list_method.replace('list_', '').rstrip('s').title().replace('_', '') + 'Summaries'
                    # Awkward — boto3 capitalization differs per resource. Try sane fallbacks.
                    items = (page.get('TrainingJobSummaries')
                             or page.get('ProcessingJobSummaries')
                             or page.get('TransformJobSummaries')
                             or [])
                    for item in items:
                        name = item.get(name_field)
                        try:
                            getattr(self.client, stop_method)(**{name_field: name})
                            self.console.print(f"[green]✓ Stopped {job_kind} job: {name}[/green]")
                        except ClientError as e:
                            self.console.print(f"[red]✗ Error stopping {job_kind} job {name}: {e}[/red]")
            except ClientError as e:
                self.console.print(f"[yellow]⚠ Could not list {job_kind} jobs: {e}[/yellow]")

    def _delete_endpoints(self):
        self.console.print("\n[bold cyan]Listing SageMaker endpoints...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_endpoints').paginate():
                for ep in page.get('Endpoints', []):
                    name = ep.get('EndpointName')
                    try:
                        self.client.delete_endpoint(EndpointName=name)
                        self.console.print(f"[green]✓ Deleted endpoint: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting endpoint {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list endpoints: {e}[/yellow]")

    def _delete_inference_components(self):
        self.console.print("\n[bold cyan]Listing SageMaker inference components...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_inference_components').paginate():
                for ic in page.get('InferenceComponents', []):
                    name = ic.get('InferenceComponentName')
                    try:
                        self.client.delete_inference_component(InferenceComponentName=name)
                        self.console.print(f"[green]✓ Deleted inference component: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting inference component {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list inference components: {e}[/yellow]")

    def _delete_endpoint_configs(self):
        self.console.print("\n[bold cyan]Listing SageMaker endpoint configs...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_endpoint_configs').paginate():
                for cfg in page.get('EndpointConfigs', []):
                    name = cfg.get('EndpointConfigName')
                    try:
                        self.client.delete_endpoint_config(EndpointConfigName=name)
                        self.console.print(f"[green]✓ Deleted endpoint config: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting endpoint config {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list endpoint configs: {e}[/yellow]")

    def _delete_models(self):
        self.console.print("\n[bold cyan]Listing SageMaker models...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_models').paginate():
                for m in page.get('Models', []):
                    name = m.get('ModelName')
                    try:
                        self.client.delete_model(ModelName=name)
                        self.console.print(f"[green]✓ Deleted model: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting model {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list models: {e}[/yellow]")

    def _delete_pipelines(self):
        self.console.print("\n[bold cyan]Listing SageMaker pipelines...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_pipelines').paginate():
                for p in page.get('PipelineSummaries', []):
                    name = p.get('PipelineName')
                    try:
                        self.client.delete_pipeline(PipelineName=name)
                        self.console.print(f"[green]✓ Deleted pipeline: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting pipeline {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list pipelines: {e}[/yellow]")

    def _delete_feature_groups(self):
        self.console.print("\n[bold cyan]Listing SageMaker feature groups...[/bold cyan]")
        try:
            response = self.client.list_feature_groups()
            for fg in response.get('FeatureGroupSummaries', []):
                name = fg.get('FeatureGroupName')
                try:
                    self.client.delete_feature_group(FeatureGroupName=name)
                    self.console.print(f"[green]✓ Deleted feature group: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting feature group {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list feature groups: {e}[/yellow]")

    def _delete_notebook_instances(self):
        self.console.print("\n[bold cyan]Listing SageMaker notebook instances...[/bold cyan]")
        try:
            for page in self.client.get_paginator('list_notebook_instances').paginate():
                for nb in page.get('NotebookInstances', []):
                    name = nb.get('NotebookInstanceName')
                    status = nb.get('NotebookInstanceStatus')
                    try:
                        if status == 'InService':
                            self.client.stop_notebook_instance(NotebookInstanceName=name)
                            # Don't wait for stopping — caller can re-run.
                            self.console.print(f"[yellow]Stopping notebook (will need re-run to delete): {name}[/yellow]")
                            continue
                        self.client.delete_notebook_instance(NotebookInstanceName=name)
                        self.console.print(f"[green]✓ Deleted notebook instance: {name}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting notebook {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list notebook instances: {e}[/yellow]")

    def _delete_apps_and_domains(self):
        self.console.print("\n[bold cyan]Listing SageMaker Studio domains...[/bold cyan]")
        try:
            domains = []
            response = self.client.list_domains()
            domains.extend(response.get('Domains', []))
            while response.get('NextToken'):
                response = self.client.list_domains(NextToken=response['NextToken'])
                domains.extend(response.get('Domains', []))
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list domains: {e}[/yellow]")
            return

        for d in domains:
            domain_id = d.get('DomainId')
            domain_name = d.get('DomainName')
            try:
                # Delete apps first
                try:
                    apps_response = self.client.list_apps(DomainIdEquals=domain_id)
                    for app in apps_response.get('Apps', []):
                        if app.get('Status') == 'Deleted':
                            continue
                        try:
                            self.client.delete_app(
                                DomainId=domain_id,
                                UserProfileName=app.get('UserProfileName', ''),
                                AppType=app.get('AppType'),
                                AppName=app.get('AppName'),
                            )
                        except ClientError as e:
                            self.console.print(f"[yellow]⚠ Could not delete app {app.get('AppName')}: {e}[/yellow]")
                except ClientError:
                    pass

                # Delete user profiles
                try:
                    profiles = self.client.list_user_profiles(DomainIdEquals=domain_id)
                    for prof in profiles.get('UserProfiles', []):
                        try:
                            self.client.delete_user_profile(
                                DomainId=domain_id,
                                UserProfileName=prof.get('UserProfileName'),
                            )
                        except ClientError as e:
                            self.console.print(f"[yellow]⚠ Could not delete user profile: {e}[/yellow]")
                except ClientError:
                    pass

                self.client.delete_domain(DomainId=domain_id, RetentionPolicy={'HomeEfsFileSystem': 'Delete'})
                self.console.print(f"[green]✓ Deleted Studio domain: {domain_name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting domain {domain_name}: {e}[/red]")

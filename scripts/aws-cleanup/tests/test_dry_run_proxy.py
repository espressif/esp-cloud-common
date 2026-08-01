"""Guard tests for the dry-run proxy.

These exist because a destructive-prefix denylist can never be complete —
verbs like ``schedule_key_deletion`` don't match any obvious destructive
prefix, and a missed verb means a "dry run" that mutates the account. The
proxy therefore uses a *read-only* allowlist so any verb we haven't seen is
intercepted by default. Don't relax this without thinking very hard.

The MUTATING_VERBS list below is the cross-service sample of verbs actually
called by service modules. When you add a new module, add any new mutating
verbs it calls. The list is the contract: if a verb fires here, it will
fire in production too.

Run: ``python3 -m pytest tests/`` from ``scripts/aws-cleanup/``.
"""

from io import StringIO
import pytest
from rich.console import Console

from services.base import _DryRunClient, _NoopWaiter, _READ_ONLY_PREFIXES


# --- Read-prefix allowlist coverage --------------------------------------

# Every prefix in the allowlist must let calls pass through. We sample one
# realistic verb per prefix.
READ_VERBS_BY_PREFIX = [
    ('list_', 'list_things'),
    ('describe_', 'describe_key'),
    ('get_', 'get_distribution_config'),
    ('head_', 'head_object'),
    ('lookup_', 'lookup_events'),
    ('query_', 'query_log_events'),
    ('search_', 'search_resources'),
    ('select_', 'select_object_content'),
    ('check_', 'check_dns_availability'),
    ('test_', 'test_event_pattern'),
    ('estimate_', 'estimate_template_cost'),
    ('preview_', 'preview_agent'),
    ('batch_get_', 'batch_get_secret_value'),
    ('batch_describe_', 'batch_describe_simulation_job'),
]


# --- Mutating-verb coverage ----------------------------------------------

# Sample of verbs across every service module. Every one of these MUST be
# intercepted by the dry-run proxy. Grouped by source module for sanity.
MUTATING_VERBS = [
    # base / kms — verbs a destructive-prefix denylist would miss
    'schedule_key_deletion', 'cancel_key_deletion',
    # iot
    'delete_thing', 'detach_thing_principal', 'detach_policy',
    'update_certificate', 'delete_certificate', 'delete_policy',
    'delete_topic_rule', 'delete_thing_group', 'delete_billing_group',
    'deprecate_thing_type', 'delete_thing_type', 'delete_provisioning_template',
    'update_domain_configuration', 'delete_domain_configuration',
    'update_authorizer', 'delete_authorizer', 'delete_job',
    # sns / sqs
    'unsubscribe', 'delete_topic', 'delete_queue', 'delete_endpoint',
    'delete_platform_application',
    # eventbridge
    'remove_targets', 'delete_rule', 'delete_event_bus', 'delete_archive',
    'delete_api_destination', 'delete_connection', 'cancel_replay',
    'delete_schedule', 'delete_schedule_group',
    # s3
    'put_bucket_policy', 'empty_bucket', 'delete_objects', 'delete_bucket',
    # cloudformation
    'delete_stack', 'update_termination_protection', 'delete_stack_set',
    'delete_stack_instances',
    # iam — the big expansion
    'detach_role_policy', 'delete_role_policy', 'delete_role',
    'remove_role_from_instance_profile', 'delete_instance_profile',
    'detach_user_policy', 'delete_user_policy', 'delete_user',
    'delete_login_profile', 'deactivate_mfa_device', 'delete_virtual_mfa_device',
    'delete_signing_certificate', 'delete_ssh_public_key',
    'delete_service_specific_credential', 'remove_user_from_group',
    'detach_group_policy', 'delete_group_policy', 'delete_group',
    'delete_policy_version', 'delete_open_id_connect_provider',
    'delete_saml_provider', 'delete_server_certificate',
    # ec2
    'terminate_instances', 'delete_volume', 'delete_snapshot',
    'deregister_image', 'delete_key_pair', 'release_address',
    'cancel_capacity_reservation', 'delete_nat_gateway',
    'delete_network_interface', 'delete_launch_template', 'delete_placement_group',
    # rds / elasticache / dynamodb
    'modify_db_instance', 'modify_db_cluster', 'delete_db_instance',
    'delete_db_cluster', 'delete_db_snapshot', 'delete_db_cluster_snapshot',
    'delete_db_proxy', 'delete_event_subscription', 'delete_db_parameter_group',
    'delete_db_cluster_parameter_group', 'delete_option_group',
    'delete_db_subnet_group', 'delete_replication_group', 'delete_cache_cluster',
    'delete_user_group', 'delete_cache_parameter_group',
    'delete_cache_subnet_group', 'delete_table',
    # ecs / ecr / efs
    'update_service', 'delete_service', 'stop_task', 'delete_cluster',
    'deregister_task_definition', 'delete_repository', 'delete_access_point',
    'delete_mount_target', 'delete_file_system',
    # cognito (incl identity pools)
    'delete_user_pool', 'delete_user_pool_domain', 'delete_identity_pool',
    # ssm
    'delete_parameters', 'delete_association', 'delete_maintenance_window',
    'delete_patch_baseline', 'delete_document',
    # glue
    'delete_trigger', 'delete_workflow', 'delete_ml_transform',
    'delete_crawler', 'delete_database', 'delete_connection', 'delete_registry',
    # athena / opensearch
    'delete_named_query', 'delete_work_group', 'delete_domain',
    'delete_collection', 'delete_security_policy', 'delete_access_policy',
    'delete_vpc_endpoint',
    # cloudfront
    'update_distribution', 'delete_distribution',
    'delete_field_level_encryption_config',
    'delete_cloud_front_origin_access_identity', 'delete_origin_access_control',
    'delete_cache_policy', 'delete_origin_request_policy',
    'delete_response_headers_policy', 'delete_function', 'delete_key_value_store',
    # wafv2
    'delete_web_acl', 'delete_rule_group', 'delete_ip_set',
    'delete_regex_pattern_set',
    # cloudwatch
    'delete_log_group', 'delete_alarms', 'delete_dashboards',
    'delete_insight_rules', 'stop_canary', 'delete_canary',
    # acm + acm pca
    'delete_certificate_authority', 'update_certificate_authority',
    # apigateway
    'delete_rest_api', 'delete_api', 'delete_usage_plan', 'delete_usage_plan_key',
    'delete_api_key', 'delete_domain_name', 'delete_client_certificate',
    # stepfunctions / appsync
    'delete_state_machine', 'delete_activity', 'delete_graphql_api',
    # kinesis
    'delete_stream', 'delete_delivery_stream', 'delete_application',
    # secretsmanager
    'delete_secret',
    # lambda
    'delete_function',
    # ses
    'delete_contact_list', 'delete_email_template', 'delete_configuration_set',
    'delete_email_identity', 'delete_receipt_rule_set',
    'delete_custom_verification_email_template', 'delete_template',
    'delete_identity',
    # sagemaker
    'delete_endpoint', 'delete_endpoint_config', 'delete_model',
    'delete_pipeline', 'delete_feature_group', 'delete_notebook_instance',
    'stop_notebook_instance', 'delete_app', 'delete_user_profile',
    'delete_inference_component', 'stop_training_job', 'stop_processing_job',
    'stop_transform_job',
    # emr
    'terminate_job_flows', 'stop_application',
    # bedrock
    'delete_provisioned_model_throughput', 'delete_custom_model',
    'delete_guardrail', 'delete_agent', 'delete_knowledge_base',
    'delete_data_source',
    # quicksight
    'delete_dashboard', 'delete_analysis', 'delete_data_set', 'delete_theme',
    'delete_folder',
    # codesuite
    'delete_project', 'delete_source_credentials', 'delete_deployment_config',
    # cloudtrail
    'delete_trail', 'delete_event_data_store', 'delete_channel',
    'update_event_data_store',
]


# --- Test fixtures -------------------------------------------------------

class _FakeClient:
    """Read methods return canned responses; mutating methods raise.

    Mutating methods are added dynamically inside each test so we always
    have a fresh, raising fake for the verb under test.
    """

    def __init__(self):
        self.read_calls = []

    def list_things(self, **kw):
        self.read_calls.append(('list_things', kw))
        return {'Things': []}

    def describe_key(self, **kw):
        self.read_calls.append(('describe_key', kw))
        return {'KeyMetadata': {}}

    def get_distribution_config(self, **kw):
        self.read_calls.append(('get_distribution_config', kw))
        return {'ETag': 'x'}

    def head_object(self, **kw):
        self.read_calls.append(('head_object', kw))
        return {}

    def lookup_events(self, **kw):
        self.read_calls.append(('lookup_events', kw))
        return {}

    def query_log_events(self, **kw):
        self.read_calls.append(('query_log_events', kw))
        return {}

    def search_resources(self, **kw):
        self.read_calls.append(('search_resources', kw))
        return {}

    def select_object_content(self, **kw):
        self.read_calls.append(('select_object_content', kw))
        return {}

    def check_dns_availability(self, **kw):
        self.read_calls.append(('check_dns_availability', kw))
        return {}

    def test_event_pattern(self, **kw):
        self.read_calls.append(('test_event_pattern', kw))
        return {}

    def estimate_template_cost(self, **kw):
        self.read_calls.append(('estimate_template_cost', kw))
        return {}

    def preview_agent(self, **kw):
        self.read_calls.append(('preview_agent', kw))
        return {}

    def batch_get_secret_value(self, **kw):
        self.read_calls.append(('batch_get_secret_value', kw))
        return {}

    def batch_describe_simulation_job(self, **kw):
        self.read_calls.append(('batch_describe_simulation_job', kw))
        return {}

    def get_paginator(self, name):
        return f'paginator:{name}'


@pytest.fixture
def proxy():
    real = _FakeClient()
    console = Console(file=StringIO())
    return _DryRunClient(real, 'fake', console), real


# --- Tests ---------------------------------------------------------------

@pytest.mark.parametrize('prefix,verb', READ_VERBS_BY_PREFIX)
def test_read_prefix_passes_through(proxy, prefix, verb):
    """Every prefix in the allowlist must let calls reach the real client."""
    p, real = proxy
    getattr(p, verb)()
    assert any(c[0] == verb for c in real.read_calls), \
        f'{verb} did not reach the real client'


def test_allowlist_covers_all_documented_prefixes():
    """Every prefix in READ_VERBS_BY_PREFIX must actually be in the source allowlist."""
    documented = {p for p, _ in READ_VERBS_BY_PREFIX}
    assert documented == set(_READ_ONLY_PREFIXES), \
        f"Documented prefixes drift from source.\n"\
        f"  documented but not in source: {documented - set(_READ_ONLY_PREFIXES)}\n"\
        f"  in source but not documented: {set(_READ_ONLY_PREFIXES) - documented}"


@pytest.mark.parametrize('verb', MUTATING_VERBS)
def test_mutating_verb_intercepted(proxy, verb):
    """Each known mutating verb must be intercepted, even when the underlying
    client would have raised on the call."""
    p, real = proxy
    # Plant an exploding implementation so a leak surfaces as an exception.
    def _explode(self, **kw):
        raise AssertionError(f'{verb} leaked through dry-run')
    setattr(type(real), verb, _explode)
    try:
        result = getattr(p, verb)(x=1)
        assert result == {}, f'{verb} should return {{}} stub'
    finally:
        delattr(type(real), verb)


def test_get_paginator_passes_through(proxy):
    p, _ = proxy
    assert p.get_paginator('list_things') == 'paginator:list_things'


def test_get_waiter_returns_noop(proxy):
    p, _ = proxy
    waiter = p.get_waiter('table_exists')
    assert isinstance(waiter, _NoopWaiter)
    assert waiter.wait(TableName='x') is None


def test_unknown_attribute_returns_intercepting_stub(proxy):
    """A method we have never heard of should be intercepted, not passed through."""
    p, real = proxy
    def _explode(self, **kw):
        raise AssertionError('completely unknown verb leaked')
    setattr(type(real), 'totally_made_up_verb', _explode)
    try:
        assert p.totally_made_up_verb(x=1) == {}
    finally:
        delattr(type(real), 'totally_made_up_verb')

"""ManagedTable: a DynamoDB Table that routes GSI changes through the GSI
orchestrator. Drop-in for ``aws_cdk.aws_dynamodb.Table`` plus a
``common_resources`` argument carrying the orchestrator's ARNs.
"""

from typing import Any, Optional

from aws_cdk import (
    CustomResource,
    RemovalPolicy,
    Tags,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
)
from constructs import Construct

from common import stable_logical_id

# Tag applied to every ManagedTable. The orchestrator's worker IAM scopes
# its DescribeTable/UpdateTable permissions to tables carrying this tag,
# so consumers who manage tables outside ManagedTable aren't reachable.
GSI_MANAGED_BY_TAG_KEY = "ManagedBy"
GSI_MANAGED_BY_TAG_VALUE = "gsi-infra"


class ManagedTable(dynamodb.Table):
    """DynamoDB Table that routes GSI changes through the GSI orchestrator.

    Each ``add_global_secondary_index`` call emits a ``Custom::GsiIndex``
    resource so the orchestrator can serialize them (DynamoDB rejects
    more than one online GSI change per UpdateTable).

    Args:
      common_resources: any object with attributes
        ``gsi_trigger_lambda_arn`` and ``gsi_state_machine_arn`` (set by
        ``GsiInfraCore`` on stack construction). Optional — pass ``None``
        when the table has no GSIs and you don't want to wire the
        orchestrator. ``add_global_secondary_index`` will raise if called
        without it.
      Other kwargs are passed verbatim to ``aws_cdk.aws_dynamodb.Table``.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        table_name: str,
        common_resources=None,
        **kwargs: Any,
    ) -> None:
        # table_name is mandatory: it's the input to the stable logical
        # ID, and a CDK-auto-named table can't survive a refactor (the
        # auto-derived name would change with the construct path).
        if not table_name:
            raise ValueError("ManagedTable requires an explicit `table_name`.")
        # Default to PAY_PER_REQUEST: tested with only this mode for now
        kwargs.setdefault("billing_mode", dynamodb.BillingMode.PAY_PER_REQUEST)
        super().__init__(scope, id, table_name=table_name, **kwargs)
        self._common_resources = common_resources
        self._gsi_resources: list[CustomResource] = []
        self._stable_id = table_name

        # Logical-ID input is the physical table_name
        # (`stable_logical_id("DDBTable", table_name)`).
        self.node.default_child.override_logical_id(
            stable_logical_id("DDBTable", table_name)
        )
        # Public so GsiReadinessGate can include GSI names in its
        # WaitCondition digest — a GSI added or removed changes the digest,
        # which is what makes the gate re-wait on UPDATE instead of reusing
        # a stale, already-satisfied WaitCondition.
        self.gsi_names: set[str] = set()

        # Tag scopes the worker's IAM so it can only touch tables we manage.
        Tags.of(self).add(GSI_MANAGED_BY_TAG_KEY, GSI_MANAGED_BY_TAG_VALUE)

    @property
    def stable_id(self) -> str:
        """The literal ``table_name`` (never a CDK token), stable across synths.

        ``.table_name`` on an L2 Table resolves to a ``Ref`` token, whose id
        varies with construct order between synths — unsuitable for anything that
        must be deterministic (e.g. hashing into a logical ID). Use this instead.
        """
        return self._stable_id

    # GSIs here are created out-of-band (Custom::GsiIndex), so the parent Table
    # never registers them and CDK's ``has_index`` stays False — which makes the
    # inherited read grants omit the ``table/.../index/*`` ARN. A consumer that
    # Queries a GSI then gets AccessDenied even though it holds read access on the
    # base table. Re-add index read permissions on every read grant so GSI queries
    # authorize. (Writes never target a GSI directly, so write grants need no index.)
    _INDEX_READ_ACTIONS = (
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:GetItem",
        "dynamodb:BatchGetItem",
        "dynamodb:ConditionCheckItem",
        "dynamodb:DescribeTable",
    )

    def _grant_index_read(self, grantee: iam.IGrantable) -> None:
        iam.Grant.add_to_principal(
            grantee=grantee,
            actions=list(self._INDEX_READ_ACTIONS),
            resource_arns=[f"{self.table_arn}/index/*"],
        )

    def grant_read_data(self, grantee: iam.IGrantable) -> iam.Grant:
        grant = super().grant_read_data(grantee)
        self._grant_index_read(grantee)
        return grant

    def grant_read_write_data(self, grantee: iam.IGrantable) -> iam.Grant:
        grant = super().grant_read_write_data(grantee)
        self._grant_index_read(grantee)
        return grant

    def add_global_secondary_index(
        self,
        *,
        index_name: str,
        partition_key: dynamodb.Attribute,
        sort_key: Optional[dynamodb.Attribute] = None,
        projection_type: dynamodb.ProjectionType = dynamodb.ProjectionType.ALL,
        non_key_attributes: Optional[list[str]] = None,
        delete_index: bool = True,
        **_: Any,
    ) -> None:
        if self._common_resources is None:
            raise ValueError(
                f"ManagedTable {self.table_name!r}: add_global_secondary_index "
                "requires `common_resources` (with gsi_trigger_lambda_arn / "
                "gsi_state_machine_arn). Pass it to the ManagedTable constructor."
            )
        if index_name in self.gsi_names:
            raise ValueError(f"GSI {index_name!r} declared twice on table {self.table_name}")
        self.gsi_names.add(index_name)

        operation, attribute_definitions = _build_gsi_update(
            index_name=index_name,
            partition_key=partition_key,
            sort_key=sort_key,
            projection_type=projection_type,
            non_key_attributes=non_key_attributes,
        )

        resource = CustomResource(
            self, f"GsiIndex_{index_name}",
            service_token=self._common_resources.gsi_trigger_lambda_arn,
            resource_type="Custom::GsiIndex",
            properties={
                "state_machine_arn": self._common_resources.gsi_state_machine_arn,
                "table_name": self.table_name,
                "operation": operation,
                "attribute_definitions": attribute_definitions,
            },
            removal_policy=RemovalPolicy.DESTROY if delete_index else RemovalPolicy.RETAIN,
        )
        resource.node.default_child.override_logical_id(
            stable_logical_id("GsiIndex", f"{self._stable_id}-{index_name}")
        )

        if self.node.default_child is not None:
            resource.node.add_dependency(self.node.default_child) #resource.node is the current resource i.e. GSI depend on self.node.default_child (child of self node ManagedTable) i.e. CfnTable
        # Chain GSIs so CFN deploys them sequentially (DynamoDB rejects parallel UpdateTable calls with ResourceInUseException).
        if self._gsi_resources:
            previous = self._gsi_resources[-1].node.default_child
            if previous is not None:
                resource.node.add_dependency(previous)
        self._gsi_resources.append(resource)


def _build_gsi_update(
    *,
    index_name: str,
    partition_key: dynamodb.Attribute,
    sort_key: Optional[dynamodb.Attribute],
    projection_type: dynamodb.ProjectionType,
    non_key_attributes: Optional[list[str]],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Build a single GSI Create payload for an AWS UpdateTable request.

    Mirrors the AWS UpdateTable shape so the Go worker can consume it verbatim.
    ProvisionedThroughput is omitted; ManagedTable defaults the base table to
    PAY_PER_REQUEST so per-GSI throughput is not required.

    Args:
        index_name: GSI name.
        partition_key: HASH key attribute for the index.
        sort_key: optional RANGE key attribute.
        projection_type: ALL, KEYS_ONLY, or INCLUDE.
        non_key_attributes: required when projection_type is INCLUDE; ignored otherwise.

    Returns:
        operation: a GlobalSecondaryIndexUpdate entry with a "Create" key,
            ready to be placed in UpdateTable's GlobalSecondaryIndexUpdates list.
            Shape:
                {"Create": {
                    "IndexName": <str>,
                    "KeySchema": [{"AttributeName": <str>, "KeyType": "HASH"},
                                  {"AttributeName": <str>, "KeyType": "RANGE"}],  # RANGE only if sort_key
                    "Projection": {"ProjectionType": "ALL"|"KEYS_ONLY"|"INCLUDE",
                                   "NonKeyAttributes": [<str>, ...]},              # only if INCLUDE
                }}
        attribute_definitions: AttributeDefinitions entries for this GSI's keys,
            to be merged into UpdateTable's AttributeDefinitions input.
            Shape: list of {"AttributeName": <str>, "AttributeType": "S"|"N"|"B"},
            partition key first, then sort key if present. Example:
                [{"AttributeName": "userId",    "AttributeType": "S"},
                 {"AttributeName": "createdAt", "AttributeType": "N"}]
    """
    key_schema = [{"AttributeName": partition_key.name, "KeyType": "HASH"}]
    attribute_definitions = [
        {"AttributeName": partition_key.name, "AttributeType": _attr_type(partition_key.type)}
    ]
    if sort_key is not None:
        key_schema.append({"AttributeName": sort_key.name, "KeyType": "RANGE"})
        attribute_definitions.append(
            {"AttributeName": sort_key.name, "AttributeType": _attr_type(sort_key.type)}
        )

    projection: dict[str, Any] = {"ProjectionType": _proj_type(projection_type)}
    if projection_type == dynamodb.ProjectionType.INCLUDE:
        if not non_key_attributes:
            raise ValueError(f"GSI {index_name!r}: non_key_attributes required for INCLUDE projection")
        projection["NonKeyAttributes"] = list(non_key_attributes)

    operation = {
        "Create": {
            "IndexName": index_name,
            "KeySchema": key_schema,
            "Projection": projection,
        }
    }
    return operation, attribute_definitions


def _attr_type(t: dynamodb.AttributeType) -> str:
    return {
        dynamodb.AttributeType.STRING: "S",
        dynamodb.AttributeType.NUMBER: "N",
        dynamodb.AttributeType.BINARY: "B",
    }[t]


def _proj_type(p: dynamodb.ProjectionType) -> str:
    return {
        dynamodb.ProjectionType.ALL: "ALL",
        dynamodb.ProjectionType.KEYS_ONLY: "KEYS_ONLY",
        dynamodb.ProjectionType.INCLUDE: "INCLUDE",
    }[p]

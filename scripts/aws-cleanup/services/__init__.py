# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Service cleanup registry.

Order matters for ``--service all``: managed/wrapper services that hold
references to other resources go first so the underlying resources can then
be cleaned up directly. Network/storage primitives go before the things
that depend on them being unused.
"""

from .acm import ACMCleanup
from .apigateway import APIGatewayCleanup
from .appsync import AppSyncCleanup
from .athena import AthenaCleanup
from .bedrock import BedrockCleanup
from .cloudformation import CloudFormationCleanup
from .cloudfront import CloudFrontCleanup
from .cloudtrail import CloudTrailCleanup
from .cloudwatch import CloudWatchCleanup
from .codesuite import CodeSuiteCleanup
from .cognito import CognitoCleanup
from .dynamodb import DynamoDBCleanup
from .ec2 import EC2Cleanup
from .ecr import ECRCleanup
from .ecs import ECSCleanup
from .efs import EFSCleanup
from .elasticache import ElastiCacheCleanup
from .emr import EMRCleanup
from .eventbridge import EventBridgeCleanup
from .glue import GlueCleanup
from .iam import IAMCleanup
from .iot import IoTCleanup
from .kinesis import KinesisCleanup
from .kms import KMSCleanup
from .lambda_ import LambdaCleanup
from .opensearch import OpenSearchCleanup
from .quicksight import QuickSightCleanup
from .rds import RDSCleanup
from .route53 import Route53Cleanup
from .s3 import S3Cleanup
from .sagemaker import SageMakerCleanup
from .secretsmanager import SecretsManagerCleanup
from .ses import SESCleanup
from .sns import SNSCleanup
from .sqs import SQSCleanup
from .ssm import SSMCleanup
from .stepfunctions import StepFunctionsCleanup
from .wafv2 import WAFv2Cleanup


# Ordering rationale:
#   - CloudFormation first: deleting stacks cascades to many dependents.
#   - High-level "wrapper" services (API Gateway, AppSync, Step Functions, ECS,
#     SageMaker, EMR, Bedrock, CodeSuite, QuickSight) first.
#   - Compute (Lambda, EC2) before the storage/data they may have held open.
#   - Glue/Athena before S3 (they reference S3 buckets and DBs).
#   - Stateful data services (RDS, ElastiCache, OpenSearch, DynamoDB).
#   - Edge/network (CloudFront, WAFv2, ACM, Route53) after compute is gone.
#   - Bulk persistence (S3, ECR, EFS) after consumers are gone.
#   - Identity & secret stores last — many things depend on them.
#   - CloudTrail last and opt-in only.
REGISTRY = [
    CloudFormationCleanup,
    APIGatewayCleanup,
    AppSyncCleanup,
    StepFunctionsCleanup,
    ECSCleanup,
    SageMakerCleanup,
    EMRCleanup,
    BedrockCleanup,
    CodeSuiteCleanup,
    QuickSightCleanup,
    LambdaCleanup,
    EC2Cleanup,
    EventBridgeCleanup,
    SQSCleanup,
    SNSCleanup,
    SESCleanup,
    KinesisCleanup,
    GlueCleanup,
    AthenaCleanup,
    RDSCleanup,
    ElastiCacheCleanup,
    DynamoDBCleanup,
    OpenSearchCleanup,
    CognitoCleanup,
    IoTCleanup,
    WAFv2Cleanup,
    CloudFrontCleanup,
    ACMCleanup,
    Route53Cleanup,
    CloudWatchCleanup,
    S3Cleanup,
    ECRCleanup,
    EFSCleanup,
    IAMCleanup,
    SecretsManagerCleanup,
    SSMCleanup,
    KMSCleanup,
    CloudTrailCleanup,  # opt-in via --include-cloudtrail
]


REGISTRY_BY_NAME = {cls.name: cls for cls in REGISTRY}


def supported_services():
    return [cls.name for cls in REGISTRY] + ['all']

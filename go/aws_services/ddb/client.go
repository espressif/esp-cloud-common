// Package ddb provides a narrow DynamoDB control-plane client interface
// for callers that only operate on table metadata (DescribeTable,
// UpdateTable). A wider data-plane interface lives in higher-layer
// packages once they need it.
package ddb

import (
	"context"
	"sync"

	"github.com/aws/aws-sdk-go-v2/service/dynamodb"

	"github.com/espressif/esp-cloud-common/go/aws_services/awsconfig"
)

// ControlPlaneClient is the subset of DynamoDB used by control-plane
// callers (e.g. the GSI orchestrator worker). Mocks need only implement
// this interface.
type ControlPlaneClient interface {
	DescribeTable(ctx context.Context, params *dynamodb.DescribeTableInput, optFns ...func(*dynamodb.Options)) (*dynamodb.DescribeTableOutput, error)
	UpdateTable(ctx context.Context, params *dynamodb.UpdateTableInput, optFns ...func(*dynamodb.Options)) (*dynamodb.UpdateTableOutput, error)
}

var (
	client ControlPlaneClient
	once   sync.Once
)

func defaultClient() ControlPlaneClient {
	cfg, err := awsconfig.Load(context.Background())
	if err != nil {
		panic("ddb: failed to load AWS SDK config: " + err.Error())
	}
	return dynamodb.NewFromConfig(cfg)
}

// SetClient overrides the active control-plane client. Tests use this to
// inject mocks.
func SetClient(c ControlPlaneClient) { client = c }

// GetClient returns the active client, lazy-initializing the AWS SDK
// client if SetClient hasn't been called.
func GetClient() ControlPlaneClient {
	once.Do(func() {
		if client == nil {
			client = defaultClient()
		}
	})
	return client
}

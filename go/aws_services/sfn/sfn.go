// SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
//
// SPDX-License-Identifier: Apache-2.0

// Package sfn wraps the AWS Step Functions client with esp-cloud-common
// error handling and a single client lookup point. The active client is
// the AWS SDK client by default; tests inject a mock via [SetClient].
package sfn

import (
	"context"
	"fmt"
	"sync"

	"github.com/aws/aws-sdk-go-v2/aws"
	awssdk "github.com/aws/aws-sdk-go-v2/service/sfn"
	sfntypes "github.com/aws/aws-sdk-go-v2/service/sfn/types"

	"github.com/espressif/esp-cloud-common/go/aws_services/awsconfig"
	"github.com/espressif/esp-cloud-common/go/util"
)

// Client is the subset of the AWS SDK Step Functions client surface that
// this package uses. Mocks need only satisfy this narrow interface.
type Client interface {
	StartExecution(ctx context.Context, params *awssdk.StartExecutionInput, optFns ...func(*awssdk.Options)) (*awssdk.StartExecutionOutput, error)
	StopExecution(ctx context.Context, params *awssdk.StopExecutionInput, optFns ...func(*awssdk.Options)) (*awssdk.StopExecutionOutput, error)
	DescribeExecution(ctx context.Context, params *awssdk.DescribeExecutionInput, optFns ...func(*awssdk.Options)) (*awssdk.DescribeExecutionOutput, error)
	ListExecutions(ctx context.Context, params *awssdk.ListExecutionsInput, optFns ...func(*awssdk.Options)) (*awssdk.ListExecutionsOutput, error)
}

var (
	client Client
	once   sync.Once
)

func defaultClient() Client {
	cfg, err := awsconfig.Load(context.Background())
	if err != nil {
		panic("sfn: failed to load AWS SDK config: " + err.Error())
	}
	return awssdk.NewFromConfig(cfg)
}

// SetClient overrides the active SFN client. Tests use this to inject mocks.
func SetClient(c Client) { client = c }

// GetClient returns the active SFN client, lazy-initializing the AWS SDK
// client if SetClient hasn't been called.
func GetClient() Client {
	once.Do(func() {
		if client == nil {
			client = defaultClient()
		}
	})
	return client
}

// StartExecution kicks off a new state machine execution and returns its ARN.
func StartExecution(ctx context.Context, stateMachineArn, input string) (string, error) {
	out, err := GetClient().StartExecution(ctx, &awssdk.StartExecutionInput{
		StateMachineArn: aws.String(stateMachineArn),
		Input:           aws.String(input),
	})
	if err != nil {
		return "", util.NewCustomError(err, "failed to start state machine execution")
	}
	return aws.ToString(out.ExecutionArn), nil
}

// StartExecutionNamed starts an execution with an explicit name (for
// correlation/observability) and returns its ARN.
func StartExecutionNamed(ctx context.Context, stateMachineArn, input, name string) (string, error) {
	in := &awssdk.StartExecutionInput{
		StateMachineArn: aws.String(stateMachineArn),
		Input:           aws.String(input),
	}
	if name != "" {
		in.Name = aws.String(name)
	}
	out, err := GetClient().StartExecution(ctx, in)
	if err != nil {
		return "", util.NewCustomError(err, "failed to start state machine execution")
	}
	return aws.ToString(out.ExecutionArn), nil
}

// ExecutionSummary is a trimmed view of a ListExecutions item.
type ExecutionSummary struct {
	Name   string
	Arn    string
	Status sfntypes.ExecutionStatus
}

// ListExecutions returns recent executions for a state machine, newest-first,
// up to maxItems. Errors are wrapped with %w so callers can classify them.
func ListExecutions(ctx context.Context, stateMachineArn string, maxItems int) ([]ExecutionSummary, error) {
	limit := int32(maxItems)
	out, err := GetClient().ListExecutions(ctx, &awssdk.ListExecutionsInput{
		StateMachineArn: aws.String(stateMachineArn),
		MaxResults:      limit,
	})
	if err != nil {
		return nil, fmt.Errorf("list state machine executions: %w", err)
	}
	res := make([]ExecutionSummary, 0, len(out.Executions))
	for _, e := range out.Executions {
		res = append(res, ExecutionSummary{
			Name:   aws.ToString(e.Name),
			Arn:    aws.ToString(e.ExecutionArn),
			Status: e.Status,
		})
	}
	return res, nil
}

// StopExecution aborts a running execution. Best-effort — callers
// typically log and proceed if this fails.
func StopExecution(ctx context.Context, executionArn, cause string) error {
	_, err := GetClient().StopExecution(ctx, &awssdk.StopExecutionInput{
		ExecutionArn: aws.String(executionArn),
		Cause:        aws.String(cause),
	})
	if err != nil {
		return util.NewCustomError(err, "failed to stop state machine execution")
	}
	return nil
}

// DescribeExecution returns the current status and Cause of an execution.
func DescribeExecution(ctx context.Context, executionArn string) (sfntypes.ExecutionStatus, string, error) {
	out, err := GetClient().DescribeExecution(ctx, &awssdk.DescribeExecutionInput{
		ExecutionArn: aws.String(executionArn),
	})
	if err != nil {
		return "", "", util.NewCustomError(err, "failed to describe state machine execution")
	}
	return out.Status, aws.ToString(out.Cause), nil
}

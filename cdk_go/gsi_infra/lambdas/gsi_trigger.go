// SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
//
// SPDX-License-Identifier: Apache-2.0

// Package gsi_infra hosts shared logic for the GSI trigger Lambdas.
package gsi_infra

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/aws/aws-lambda-go/cfn"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"

	"github.com/espressif/esp-cloud-common/go/aws_services/sfn"
	"github.com/espressif/esp-cloud-common/go/clog"
	"github.com/espressif/esp-cloud-common/go/util"
)

type GsiResourceProperties struct {
	StateMachineArn      string                           `json:"state_machine_arn"`
	TableName            string                           `json:"table_name"`
	Operation            types.GlobalSecondaryIndexUpdate `json:"operation"`
	AttributeDefinitions []types.AttributeDefinition      `json:"attribute_definitions,omitempty"`
}

type ExecutionInput struct {
	TableName            string                           `json:"table_name"`
	Operation            types.GlobalSecondaryIndexUpdate `json:"operation"`
	AttributeDefinitions []types.AttributeDefinition      `json:"attribute_definitions,omitempty"`
}

type OnEventRequest = cfn.Event

type OnEventData struct {
	ExecutionArn string `json:"ExecutionArn"`
}

type OnEventResponse struct {
	PhysicalResourceId string      `json:"PhysicalResourceId"`
	Data               OnEventData `json:"Data,omitempty"`
}

// PhysicalResourceId must be stable across Create/Update/Delete (CFN
// rejects ID changes during deletion). The in-flight Step Functions
// execution ARN — which changes per onEvent invocation — is propagated
// via event.Data (e.g. so a subsequent Delete can stop the prior
// execution) without repurposing the ID.
const executionArnKey = "ExecutionArn"

func OnEvent(ctx context.Context, raw json.RawMessage) (OnEventResponse, error) {
	var ev OnEventRequest
	if err := json.Unmarshal(raw, &ev); err != nil {
		return OnEventResponse{}, util.NewCustomError(err, "decode provider event")
	}

	props, err := decodeProperties(ev.ResourceProperties)
	if err != nil {
		return OnEventResponse{}, err
	}

	switch ev.RequestType {
	case cfn.RequestCreate, cfn.RequestUpdate:
		indexName, err := indexNameFromOperation(props.Operation)
		if err != nil {
			return OnEventResponse{}, err
		}
		// DynamoDB has no in-place GSI update; the worker delete-and-recreates
		// when a Create finds an existing GSI with a different schema.
		return startExecution(ctx, props, props.Operation, physicalResourceID(props.TableName, indexName))
	case cfn.RequestDelete:
		// Echo back the ID CFN sent — recomputing it would reject the delete
		// if the ID format ever changed between the original Create and now.
		return startDelete(ctx, raw, props, ev.PhysicalResourceID)
	default:
		return OnEventResponse{}, util.NewCustomError(
			fmt.Errorf("unexpected RequestType %q", ev.RequestType),
			"OnEvent",
		)
	}
}

func startExecution(ctx context.Context, props GsiResourceProperties, op types.GlobalSecondaryIndexUpdate, physicalID string) (OnEventResponse, error) {
	input, err := marshalExecutionInput(ExecutionInput{
		TableName:            props.TableName,
		Operation:            op,
		AttributeDefinitions: props.AttributeDefinitions,
	})
	if err != nil {
		return OnEventResponse{}, err
	}
	indexName, err := indexNameFromOperation(op)
	if err != nil {
		return OnEventResponse{}, err
	}
	var name string
	if op.Create != nil {
		name = GSICreateExecutionName(props.TableName, indexName)
	} else {
		name = GSIDeleteExecutionName(props.TableName, indexName)
	}
	arn, err := sfn.StartExecutionNamed(ctx, props.StateMachineArn, input, name)
	if err != nil {
		return OnEventResponse{}, err
	}
	return OnEventResponse{
		PhysicalResourceId: physicalID,
		Data:               OnEventData{ExecutionArn: arn},
	}, nil
}

func startDelete(ctx context.Context, raw json.RawMessage, props GsiResourceProperties, physicalID string) (OnEventResponse, error) {
	if priorArn := priorExecutionArn(raw); priorArn != "" {
		if err := sfn.StopExecution(ctx, priorArn, "Superseded by CFN delete event"); err != nil {
			clog.Warn().Err(err).Msg("stop prior execution failed; proceeding")
		}
	}

	if props.Operation.Create == nil || props.Operation.Create.IndexName == nil {
		return OnEventResponse{}, util.NewCustomError(
			errors.New("ResourceProperties.Operation.Create.IndexName is required to derive the index to delete"),
			"startDelete",
		)
	}
	deleteOp := types.GlobalSecondaryIndexUpdate{
		Delete: &types.DeleteGlobalSecondaryIndexAction{IndexName: props.Operation.Create.IndexName},
	}
	return startExecution(ctx, props, deleteOp, physicalID)
}

func physicalResourceID(tableName, indexName string) string {
	return "gsi:" + tableName + ":" + indexName
}

func indexNameFromOperation(op types.GlobalSecondaryIndexUpdate) (string, error) {
	switch {
	case op.Create != nil && op.Create.IndexName != nil:
		return *op.Create.IndexName, nil
	case op.Delete != nil && op.Delete.IndexName != nil:
		return *op.Delete.IndexName, nil
	}
	return "", util.NewCustomError(
		errors.New("Operation.Create.IndexName or Operation.Delete.IndexName is required"),
		"indexNameFromOperation",
	)
}

// priorExecutionArn extracts the in-flight Step Functions execution ARN
// from event.Data.ExecutionArn, as propagated by a prior onEvent call (see
// startDelete, which uses it to stop a superseded execution).
func priorExecutionArn(raw json.RawMessage) string {
	var envelope struct {
		Data map[string]interface{} `json:"Data"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return ""
	}
	if v, ok := envelope.Data[executionArnKey].(string); ok {
		return v
	}
	return ""
}

func decodeProperties(rawProps map[string]interface{}) (GsiResourceProperties, error) {
	var props GsiResourceProperties
	if len(rawProps) == 0 {
		return props, util.NewCustomError(errors.New("ResourceProperties missing"), "decodeProperties")
	}
	if err := util.ConvertAnyToAny(rawProps, &props); err != nil {
		return props, util.NewCustomError(err, "decode ResourceProperties")
	}
	if props.StateMachineArn == "" {
		return props, util.NewCustomError(errors.New("StateMachineArn is required"), "decodeProperties")
	}
	if props.TableName == "" {
		return props, util.NewCustomError(errors.New("TableName is required"), "decodeProperties")
	}
	return props, nil
}

func marshalExecutionInput(in ExecutionInput) (string, error) {
	if in.Operation.Create == nil && in.Operation.Delete == nil {
		return "", util.NewCustomError(
			errors.New("execution operation must specify Create or Delete"),
			"marshalExecutionInput",
		)
	}
	b, err := json.Marshal(in)
	if err != nil {
		return "", util.NewCustomError(err, "marshal execution input")
	}
	return string(b), nil
}

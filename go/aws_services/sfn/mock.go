// SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
//
// SPDX-License-Identifier: Apache-2.0

package sfn

import (
	"context"
	"fmt"
	"sync"

	"github.com/aws/aws-sdk-go-v2/aws"
	awssdk "github.com/aws/aws-sdk-go-v2/service/sfn"
	sfntypes "github.com/aws/aws-sdk-go-v2/service/sfn/types"
)

// Mock is a state-based test double for the Step Functions client. It
// stores executions in-memory and serves StartExecution / StopExecution /
// DescribeExecution from that state. Builders are fluent:
// NewMock().WithExecution("arn:exec:1", Running, "").
type Mock struct {
	mu         sync.RWMutex
	executions map[string]*Execution
	order      []string
	arnCounter int64

	// NextExecutionArn, if non-empty, is returned by the next StartExecution
	// (and used as the storage key); cleared after use. Otherwise a synthetic
	// "arn:mock:exec:N" ARN is generated.
	NextExecutionArn string

	// Returned once on the next matching call, then cleared.
	NextStartError    error
	NextStopError     error
	NextDescribeError error
	NextListError     error
}

// Execution captures the stored state of a single Step Functions execution.
type Execution struct {
	StateMachineArn string
	Name            string
	Input           string
	Status          sfntypes.ExecutionStatus
	Cause           string
}

// NewMock returns a mock with no executions registered.
func NewMock() *Mock {
	return &Mock{executions: map[string]*Execution{}}
}

// WithExecution seeds an execution at the given ARN.
func (m *Mock) WithExecution(arn string, status sfntypes.ExecutionStatus, cause string) *Mock {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.executions[arn] = &Execution{Status: status, Cause: cause}
	m.order = append(m.order, arn)
	return m
}

// WithExecutionFull seeds an execution with full metadata for ListExecutions tests.
func (m *Mock) WithExecutionFull(smArn, name, arn string, status sfntypes.ExecutionStatus, cause string) *Mock {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.executions[arn] = &Execution{StateMachineArn: smArn, Name: name, Status: status, Cause: cause}
	m.order = append(m.order, arn)
	return m
}

// SetStatus updates the status (and cause) of an existing execution.
// Panics if the execution has not been registered.
func (m *Mock) SetStatus(arn string, status sfntypes.ExecutionStatus, cause string) *Mock {
	m.mu.Lock()
	defer m.mu.Unlock()
	e, ok := m.executions[arn]
	if !ok {
		panic(fmt.Sprintf("sfn.Mock: execution %q not registered; call WithExecution first", arn))
	}
	e.Status = status
	e.Cause = cause
	return m
}

// GetExecution returns a copy of the stored execution, or nil if absent.
func (m *Mock) GetExecution(arn string) *Execution {
	m.mu.RLock()
	defer m.mu.RUnlock()
	e, ok := m.executions[arn]
	if !ok {
		return nil
	}
	cp := *e
	return &cp
}

// HasExecution reports whether an execution is stored at the given ARN.
func (m *Mock) HasExecution(arn string) bool {
	return m.GetExecution(arn) != nil
}

// Executions returns the ARNs of all stored executions.
func (m *Mock) Executions() []string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	arns := make([]string, 0, len(m.executions))
	for arn := range m.executions {
		arns = append(arns, arn)
	}
	return arns
}

func (m *Mock) StartExecution(_ context.Context, in *awssdk.StartExecutionInput, _ ...func(*awssdk.Options)) (*awssdk.StartExecutionOutput, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.NextStartError != nil {
		err := m.NextStartError
		m.NextStartError = nil
		return nil, err
	}
	arn := m.NextExecutionArn
	if arn != "" {
		m.NextExecutionArn = ""
	} else {
		m.arnCounter++
		arn = fmt.Sprintf("arn:mock:exec:%d", m.arnCounter)
	}
	m.executions[arn] = &Execution{
		StateMachineArn: aws.ToString(in.StateMachineArn),
		Name:            aws.ToString(in.Name),
		Input:           aws.ToString(in.Input),
		Status:          sfntypes.ExecutionStatusRunning,
	}
	m.order = append(m.order, arn)
	return &awssdk.StartExecutionOutput{ExecutionArn: aws.String(arn)}, nil
}

func (m *Mock) StopExecution(_ context.Context, in *awssdk.StopExecutionInput, _ ...func(*awssdk.Options)) (*awssdk.StopExecutionOutput, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.NextStopError != nil {
		err := m.NextStopError
		m.NextStopError = nil
		return nil, err
	}
	arn := aws.ToString(in.ExecutionArn)
	e, ok := m.executions[arn]
	if !ok {
		return nil, fmt.Errorf("ExecutionDoesNotExist: %s", arn)
	}
	e.Status = sfntypes.ExecutionStatusAborted
	if in.Cause != nil {
		e.Cause = aws.ToString(in.Cause)
	}
	return &awssdk.StopExecutionOutput{}, nil
}

func (m *Mock) DescribeExecution(_ context.Context, in *awssdk.DescribeExecutionInput, _ ...func(*awssdk.Options)) (*awssdk.DescribeExecutionOutput, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.NextDescribeError != nil {
		err := m.NextDescribeError
		m.NextDescribeError = nil
		return nil, err
	}
	arn := aws.ToString(in.ExecutionArn)
	e, ok := m.executions[arn]
	if !ok {
		return nil, fmt.Errorf("ExecutionDoesNotExist: %s", arn)
	}
	out := &awssdk.DescribeExecutionOutput{
		ExecutionArn: aws.String(arn),
		Status:       e.Status,
	}
	if e.Cause != "" {
		out.Cause = aws.String(e.Cause)
	}
	return out, nil
}

// ListExecutions returns stored executions for the requested state machine,
// newest-first (insertion order, reversed).
func (m *Mock) ListExecutions(_ context.Context, in *awssdk.ListExecutionsInput, _ ...func(*awssdk.Options)) (*awssdk.ListExecutionsOutput, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.NextListError != nil {
		err := m.NextListError
		m.NextListError = nil
		return nil, err
	}
	sm := aws.ToString(in.StateMachineArn)
	var items []sfntypes.ExecutionListItem
	// newest-first: iterate insertion order in reverse
	for i := len(m.order) - 1; i >= 0; i-- {
		arn := m.order[i]
		e := m.executions[arn]
		if e == nil || e.StateMachineArn != sm {
			continue
		}
		items = append(items, sfntypes.ExecutionListItem{
			ExecutionArn: aws.String(arn),
			Name:         aws.String(e.Name),
			Status:       e.Status,
		})
	}
	return &awssdk.ListExecutionsOutput{Executions: items}, nil
}

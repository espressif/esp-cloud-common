package ddb

import (
	"context"
	"fmt"
	"sync"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

// Mock is a control-plane-only test double: it satisfies
// [ControlPlaneClient] (DescribeTable, UpdateTable) and nothing else.
// Builders are fluent: NewMock().WithTable(...).WithGSI(...).
type Mock struct {
	mu     sync.RWMutex
	tables map[string]*tableState

	// Returned once on the next matching call, then cleared.
	NextDescribeError error
	NextUpdateError   error
}

type tableState struct {
	Status types.TableStatus
	GSIs   map[string]*types.GlobalSecondaryIndexDescription
}

// NewMock returns a mock with no tables registered.
func NewMock() *Mock {
	return &Mock{tables: map[string]*tableState{}}
}

// WithTable registers a table with the given status. Existing GSIs are
// preserved if the table is reconfigured.
func (m *Mock) WithTable(name string, status types.TableStatus) *Mock {
	m.mu.Lock()
	defer m.mu.Unlock()
	t, ok := m.tables[name]
	if !ok {
		t = &tableState{GSIs: map[string]*types.GlobalSecondaryIndexDescription{}}
		m.tables[name] = t
	}
	t.Status = status
	return m
}

// WithGSI adds a GSI with the given hash key (and optional sort key) and
// projection ALL. For non-default projections or NonKeyAttributes, use
// WithGSIDescription.
func (m *Mock) WithGSI(table, indexName, hashKey, sortKey string, status types.IndexStatus) *Mock {
	keys := []types.KeySchemaElement{{AttributeName: aws.String(hashKey), KeyType: types.KeyTypeHash}}
	if sortKey != "" {
		keys = append(keys, types.KeySchemaElement{AttributeName: aws.String(sortKey), KeyType: types.KeyTypeRange})
	}
	return m.WithGSIDescription(table, types.GlobalSecondaryIndexDescription{
		IndexName:   aws.String(indexName),
		IndexStatus: status,
		KeySchema:   keys,
		Projection:  &types.Projection{ProjectionType: types.ProjectionTypeAll},
	})
}

// WithGSIDescription installs an arbitrary GSI description on the named
// table. Panics if the table hasn't been registered yet.
func (m *Mock) WithGSIDescription(table string, gsi types.GlobalSecondaryIndexDescription) *Mock {
	m.mu.Lock()
	defer m.mu.Unlock()
	t, ok := m.tables[table]
	if !ok {
		panic(fmt.Sprintf("ddb.Mock: table %q not registered; call WithTable first", table))
	}
	if t.GSIs == nil {
		t.GSIs = map[string]*types.GlobalSecondaryIndexDescription{}
	}
	t.GSIs[aws.ToString(gsi.IndexName)] = &gsi
	return m
}

// HasGSI reports whether the named GSI exists on the table.
func (m *Mock) HasGSI(table, indexName string) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	t, ok := m.tables[table]
	if !ok {
		return false
	}
	_, ok = t.GSIs[indexName]
	return ok
}

// GSIStatus returns the status of the named GSI, or empty string if absent.
func (m *Mock) GSIStatus(table, indexName string) types.IndexStatus {
	m.mu.RLock()
	defer m.mu.RUnlock()
	t, ok := m.tables[table]
	if !ok {
		return ""
	}
	gsi, ok := t.GSIs[indexName]
	if !ok {
		return ""
	}
	return gsi.IndexStatus
}

// DescribeTable returns a TableDescription assembled from the registered
// table+GSI state. NextDescribeError, if set, is returned once and cleared.
func (m *Mock) DescribeTable(_ context.Context, in *dynamodb.DescribeTableInput, _ ...func(*dynamodb.Options)) (*dynamodb.DescribeTableOutput, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.NextDescribeError != nil {
		err := m.NextDescribeError
		m.NextDescribeError = nil
		return nil, err
	}
	t, ok := m.tables[aws.ToString(in.TableName)]
	if !ok {
		return nil, &types.ResourceNotFoundException{Message: aws.String("table not found")}
	}

	// Empty Status defaults to ACTIVE — keeps tests that never set
	// Status from looking stuck.
	status := t.Status
	if status == "" {
		status = types.TableStatusActive
	}

	gsis := make([]types.GlobalSecondaryIndexDescription, 0, len(t.GSIs))
	for _, g := range t.GSIs {
		gsis = append(gsis, *g)
	}

	return &dynamodb.DescribeTableOutput{
		Table: &types.TableDescription{
			TableName:              in.TableName,
			TableStatus:            status,
			GlobalSecondaryIndexes: gsis,
		},
	}, nil
}

// UpdateTable applies the GSI create/delete actions in input. NextUpdateError,
// if set, is returned once and cleared.
func (m *Mock) UpdateTable(_ context.Context, in *dynamodb.UpdateTableInput, _ ...func(*dynamodb.Options)) (*dynamodb.UpdateTableOutput, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.NextUpdateError != nil {
		err := m.NextUpdateError
		m.NextUpdateError = nil
		return nil, err
	}

	t, ok := m.tables[aws.ToString(in.TableName)]
	if !ok {
		return nil, &types.ResourceNotFoundException{Message: aws.String("table not found")}
	}
	if t.GSIs == nil {
		t.GSIs = map[string]*types.GlobalSecondaryIndexDescription{}
	}

	for _, u := range in.GlobalSecondaryIndexUpdates {
		switch {
		case u.Create != nil:
			name := aws.ToString(u.Create.IndexName)
			if _, exists := t.GSIs[name]; exists {
				return nil, fmt.Errorf("ValidationException: Index %s already exists", name)
			}
			t.GSIs[name] = &types.GlobalSecondaryIndexDescription{
				IndexName:   u.Create.IndexName,
				IndexStatus: types.IndexStatusActive,
				KeySchema:   u.Create.KeySchema,
				Projection:  u.Create.Projection,
			}
		case u.Delete != nil:
			name := aws.ToString(u.Delete.IndexName)
			if _, exists := t.GSIs[name]; !exists {
				return nil, fmt.Errorf("ValidationException: Index %s does not exist", name)
			}
			delete(t.GSIs, name)
		}
	}

	return &dynamodb.UpdateTableOutput{}, nil
}

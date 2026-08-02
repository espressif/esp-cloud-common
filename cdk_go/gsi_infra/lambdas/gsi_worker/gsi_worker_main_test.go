// SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
//
// SPDX-License-Identifier: Apache-2.0

package main

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"

	"github.com/espressif/esp-cloud-common/go/aws_services/ddb"
)

func TestGsiWorker(t *testing.T) {
	RegisterFailHandler(Fail)
	RunSpecs(t, "GSI Worker Suite")
}

const (
	testTable = "t"
	testIndex = "idx"
	testHash  = "pk"
)

func createOp(name, hashKey, projType string, nonKey ...string) *types.GlobalSecondaryIndexUpdate {
	return &types.GlobalSecondaryIndexUpdate{
		Create: &types.CreateGlobalSecondaryIndexAction{
			IndexName:  aws.String(name),
			KeySchema:  []types.KeySchemaElement{{AttributeName: aws.String(hashKey), KeyType: types.KeyTypeHash}},
			Projection: &types.Projection{ProjectionType: types.ProjectionType(projType), NonKeyAttributes: nonKey},
		},
	}
}

func deleteOp(name string) *types.GlobalSecondaryIndexUpdate {
	return &types.GlobalSecondaryIndexUpdate{
		Delete: &types.DeleteGlobalSecondaryIndexAction{IndexName: aws.String(name)},
	}
}

func attrDefs(hashKey string) []types.AttributeDefinition {
	return []types.AttributeDefinition{{AttributeName: aws.String(hashKey), AttributeType: types.ScalarAttributeTypeS}}
}

var _ = Describe("worker.run", func() {
	var ctx context.Context
	BeforeEach(func() { ctx = context.Background() })

	Describe("describe mode", func() {
		It("returns tableActive=true when table is ACTIVE", func() {
			m := ddb.NewMock().WithTable(testTable, types.TableStatusActive)
			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeDescribe})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeTrue())
		})

		It("returns tableActive=false when table is UPDATING", func() {
			m := ddb.NewMock().WithTable(testTable, types.TableStatusUpdating)
			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeDescribe})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeFalse())
		})
	})

	Describe("Create on absent GSI", func() {
		It("creates the GSI", func() {
			m := ddb.NewMock().WithTable(testTable, types.TableStatusActive)

			_, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createOp(testIndex, testHash, "ALL")})
			Expect(err).NotTo(HaveOccurred())
			Expect(m.HasGSI(testTable, testIndex)).To(BeTrue())
		})
	})

	Describe("Create on existing matching GSI (skip-if-matches)", func() {
		It("returns isActive=true without changing state when index ACTIVE", func() {
			m := ddb.NewMock().
				WithTable(testTable, types.TableStatusActive).
				WithGSI(testTable, testIndex, testHash, "", types.IndexStatusActive)

			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createOp(testIndex, testHash, "ALL")})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeTrue())
			Expect(m.GSIStatus(testTable, testIndex)).To(Equal(types.IndexStatusActive))
		})

		It("returns isActive=true even when index still CREATING (fire-and-forget)", func() {
			m := ddb.NewMock().
				WithTable(testTable, types.TableStatusActive).
				WithGSI(testTable, testIndex, testHash, "", types.IndexStatusCreating)

			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createOp(testIndex, testHash, "ALL"), Attempt: 2})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeTrue())
			Expect(out.Attempt).To(Equal(2))
			Expect(m.GSIStatus(testTable, testIndex)).To(Equal(types.IndexStatusCreating))
		})
	})

	Describe("Create on existing GSI with schema drift", func() {
		It("deletes the existing GSI on projection mismatch; subsequent attempt recreates and reports success", func() {
			m := ddb.NewMock().
				WithTable(testTable, types.TableStatusActive).
				WithGSIDescription(testTable, types.GlobalSecondaryIndexDescription{
					IndexName:   aws.String(testIndex),
					IndexStatus: types.IndexStatusActive,
					KeySchema:   []types.KeySchemaElement{{AttributeName: aws.String(testHash), KeyType: types.KeyTypeHash}},
					Projection:  &types.Projection{ProjectionType: types.ProjectionTypeInclude},
				})

			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createOp(testIndex, testHash, "ALL"), Attempt: 0})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeFalse())
			Expect(out.Attempt).To(Equal(1), "worker bumped Attempt because it issued Delete and must wait for the next SFN retry")
			Expect(m.HasGSI(testTable, testIndex)).To(BeFalse())

			// Recreate fires and forgets — UpdateTable accepted, success reported immediately.
			out, err = run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createOp(testIndex, testHash, "ALL"), Attempt: out.Attempt})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeTrue())
			Expect(out.Attempt).To(Equal(1), "Attempt preserved through fire-and-forget success")
			Expect(m.HasGSI(testTable, testIndex)).To(BeTrue())
		})

		It("deletes the existing GSI on key schema mismatch", func() {
			m := ddb.NewMock().
				WithTable(testTable, types.TableStatusActive).
				WithGSI(testTable, testIndex, "different_key", "", types.IndexStatusActive)

			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createOp(testIndex, testHash, "ALL")})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeFalse())
			Expect(out.Attempt).To(Equal(1), "worker bumped Attempt because it issued Delete and must wait")
			Expect(m.HasGSI(testTable, testIndex)).To(BeFalse())
		})

		It("waits without re-issuing Delete while the existing GSI is in DELETING state", func() {
			m := ddb.NewMock().
				WithTable(testTable, types.TableStatusActive).
				WithGSIDescription(testTable, types.GlobalSecondaryIndexDescription{
					IndexName:   aws.String(testIndex),
					IndexStatus: types.IndexStatusDeleting,
					KeySchema:   []types.KeySchemaElement{{AttributeName: aws.String("different_key"), KeyType: types.KeyTypeHash}},
					Projection:  &types.Projection{ProjectionType: types.ProjectionTypeAll},
				})
			m.NextUpdateError = errors.New("UpdateTable should not be called while GSI is DELETING")

			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createOp(testIndex, testHash, "ALL"), Attempt: 2})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeFalse())
			Expect(out.Attempt).To(Equal(3))
			Expect(m.GSIStatus(testTable, testIndex)).To(Equal(types.IndexStatusDeleting))
		})
	})

	Describe("Delete", func() {
		It("removes the GSI when it exists", func() {
			m := ddb.NewMock().
				WithTable(testTable, types.TableStatusActive).
				WithGSI(testTable, testIndex, testHash, "", types.IndexStatusActive)

			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: deleteOp(testIndex)})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeTrue())
			Expect(out.Attempt).To(Equal(0), "Attempt preserved through fire-and-forget Delete")
			Expect(m.HasGSI(testTable, testIndex)).To(BeFalse())
		})

		It("is a no-op when GSI absent", func() {
			m := ddb.NewMock().WithTable(testTable, types.TableStatusActive)

			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: deleteOp(testIndex)})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeTrue())
			Expect(out.Attempt).To(Equal(0), "no retry needed; idempotent success")
			Expect(m.HasGSI(testTable, testIndex)).To(BeFalse())
		})
	})

	Describe("Table not ACTIVE", func() {
		It("returns isActive=false without mutating table state", func() {
			m := ddb.NewMock().WithTable(testTable, types.TableStatusUpdating)

			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createOp(testIndex, testHash, "ALL"), Attempt: 0})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeFalse())
			Expect(out.Attempt).To(Equal(1))
			Expect(m.HasGSI(testTable, testIndex)).To(BeFalse())
		})
	})

	Describe("ResourceInUseException retry", func() {
		It("returns isActive=false; state unchanged so a retry can succeed", func() {
			m := ddb.NewMock().WithTable(testTable, types.TableStatusActive)
			m.NextUpdateError = &types.ResourceInUseException{Message: aws.String("table is busy")}

			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createOp(testIndex, testHash, "ALL"), Attempt: 0})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeFalse())
			Expect(out.Attempt).To(Equal(1))
			Expect(m.HasGSI(testTable, testIndex)).To(BeFalse())

			// NextUpdateError was consumed; the retry exercises the success path.
			_, err = run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createOp(testIndex, testHash, "ALL"), Attempt: 1})
			Expect(err).NotTo(HaveOccurred())
			Expect(m.HasGSI(testTable, testIndex)).To(BeTrue())
		})
	})

	Describe("LimitExceededException retry", func() {
		It("returns isActive=false on 'Only 1 online index can be created or deleted simultaneously per table'", func() {
			m := ddb.NewMock().WithTable(testTable, types.TableStatusActive)
			m.NextUpdateError = &types.LimitExceededException{
				Message: aws.String("Subscriber limit exceeded: Only 1 online index can be created or deleted simultaneously per table"),
			}

			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createOp(testIndex, testHash, "ALL"), Attempt: 0})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeFalse())
			Expect(out.Attempt).To(Equal(1))
			Expect(m.HasGSI(testTable, testIndex)).To(BeFalse())
		})
	})

	Describe("idempotent error strings", func() {
		It("treats 'already exists' as success on Create", func() {
			m := ddb.NewMock().WithTable(testTable, types.TableStatusActive)
			m.NextUpdateError = errors.New("ValidationException: Index idx already exists")

			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createOp(testIndex, testHash, "ALL")})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeTrue())
		})

		It("treats 'does not exist' as success on Delete", func() {
			m := ddb.NewMock().
				WithTable(testTable, types.TableStatusActive).
				WithGSI(testTable, testIndex, testHash, "", types.IndexStatusActive)
			m.NextUpdateError = errors.New("ValidationException: Index idx does not exist")

			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: deleteOp(testIndex)})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeTrue())
		})
	})

	Describe("DescribeTable error", func() {
		It("propagates the error", func() {
			m := ddb.NewMock().WithTable(testTable, types.TableStatusActive)
			m.NextDescribeError = fmt.Errorf("boom")

			_, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createOp(testIndex, testHash, "ALL")})
			Expect(err).To(HaveOccurred())
		})
	})

})

var _ = Describe("gsiMatches comparator", func() {
	It("ignores KeySchema element ordering at the AWS side", func() {
		existing := types.GlobalSecondaryIndexDescription{
			IndexName: aws.String(testIndex),
			KeySchema: []types.KeySchemaElement{
				{AttributeName: aws.String("sk"), KeyType: types.KeyTypeRange},
				{AttributeName: aws.String("pk"), KeyType: types.KeyTypeHash},
			},
			Projection: &types.Projection{ProjectionType: types.ProjectionTypeAll},
		}
		want := types.CreateGlobalSecondaryIndexAction{
			IndexName: aws.String(testIndex),
			KeySchema: []types.KeySchemaElement{
				{AttributeName: aws.String("pk"), KeyType: types.KeyTypeHash},
				{AttributeName: aws.String("sk"), KeyType: types.KeyTypeRange},
			},
			Projection: &types.Projection{ProjectionType: types.ProjectionTypeAll},
		}
		Expect(gsiMatches(existing, want)).To(BeTrue())
	})

	It("treats NonKeyAttributes as a set", func() {
		existing := types.GlobalSecondaryIndexDescription{
			IndexName:  aws.String(testIndex),
			KeySchema:  []types.KeySchemaElement{{AttributeName: aws.String("pk"), KeyType: types.KeyTypeHash}},
			Projection: &types.Projection{ProjectionType: types.ProjectionTypeInclude, NonKeyAttributes: []string{"b", "a", "c"}},
		}
		want := types.CreateGlobalSecondaryIndexAction{
			IndexName:  aws.String(testIndex),
			KeySchema:  []types.KeySchemaElement{{AttributeName: aws.String("pk"), KeyType: types.KeyTypeHash}},
			Projection: &types.Projection{ProjectionType: types.ProjectionTypeInclude, NonKeyAttributes: []string{"a", "b", "c"}},
		}
		Expect(gsiMatches(existing, want)).To(BeTrue())
	})
})

var _ = Describe("Create + Update + Delete on the same table across table states", func() {
	var ctx context.Context
	BeforeEach(func() { ctx = context.Background() })

	const idxA = "idx_a"
	const idxB = "idx_b"
	createA := func() *types.GlobalSecondaryIndexUpdate { return createOp(idxA, testHash, "ALL") }
	createAUpdated := func() *types.GlobalSecondaryIndexUpdate { return createOp(idxA, "different_key", "ALL") }
	deleteA := func() *types.GlobalSecondaryIndexUpdate { return deleteOp(idxA) }
	createB := func() *types.GlobalSecondaryIndexUpdate { return createOp(idxB, testHash, "ALL") }

	Context("when the table doesn't exist", func() {
		It("Create propagates ResourceNotFoundException", func() {
			m := ddb.NewMock()
			_, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createA(), AttributeDefinitions: attrDefs(testHash)})
			Expect(err).To(HaveOccurred())
			Expect(errors.As(err, new(*types.ResourceNotFoundException))).To(BeTrue())
		})

		It("Update (Create with different schema) propagates ResourceNotFoundException", func() {
			m := ddb.NewMock()
			_, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createAUpdated(), AttributeDefinitions: attrDefs("different_key")})
			Expect(err).To(HaveOccurred())
			Expect(errors.As(err, new(*types.ResourceNotFoundException))).To(BeTrue())
		})

		It("Delete propagates ResourceNotFoundException", func() {
			m := ddb.NewMock()
			_, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: deleteA()})
			Expect(err).To(HaveOccurred())
			Expect(errors.As(err, new(*types.ResourceNotFoundException))).To(BeTrue())
		})
	})

	Context("when the table is in UPDATING state", func() {
		It("waits without mutating state for Create, Update, or Delete", func() {
			m := ddb.NewMock().
				WithTable(testTable, types.TableStatusUpdating).
				WithGSI(testTable, idxA, testHash, "", types.IndexStatusActive)

			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createB(), AttributeDefinitions: attrDefs(testHash), Attempt: 0})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeFalse())
			Expect(out.Attempt).To(Equal(1))
			Expect(m.HasGSI(testTable, idxB)).To(BeFalse())

			out, err = run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createAUpdated(), AttributeDefinitions: attrDefs("different_key"), Attempt: 1})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeFalse())
			Expect(out.Attempt).To(Equal(2))
			Expect(m.GSIStatus(testTable, idxA)).To(Equal(types.IndexStatusActive))

			out, err = run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: deleteA(), Attempt: 2})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeFalse())
			Expect(out.Attempt).To(Equal(3))
			Expect(m.HasGSI(testTable, idxA)).To(BeTrue())
		})
	})

	Context("when the table is ACTIVE", func() {
		It("creates a new GSI, recreates it with the new schema on Update, and deletes the GSI", func() {
			m := ddb.NewMock().WithTable(testTable, types.TableStatusActive)

			_, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createA(), AttributeDefinitions: attrDefs(testHash)})
			Expect(err).NotTo(HaveOccurred())
			Expect(m.HasGSI(testTable, idxA)).To(BeTrue())

			// Update = drift → loop 1 deletes (returns false, retry), loop 2 recreates and fires-and-forgets.
			out, err := run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createAUpdated(), AttributeDefinitions: attrDefs("different_key"), Attempt: 0})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeFalse())
			Expect(m.HasGSI(testTable, idxA)).To(BeFalse())

			out, err = run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: createAUpdated(), AttributeDefinitions: attrDefs("different_key"), Attempt: out.Attempt})
			Expect(err).NotTo(HaveOccurred())
			Expect(out.IsActive).To(BeTrue())
			Expect(m.HasGSI(testTable, idxA)).To(BeTrue())

			_, err = run(ctx, m, Input{TableName: testTable, Mode: ModeApply, Operation: deleteA()})
			Expect(err).NotTo(HaveOccurred())
			Expect(m.HasGSI(testTable, idxA)).To(BeFalse())
		})
	})
})

var _ = Describe("Handler", func() {
	var ctx context.Context
	BeforeEach(func() { ctx = context.Background() })

	It("delegates to run() using the package-level DynamoDB client", func() {
		original := ddb.GetClient()
		DeferCleanup(func() { ddb.SetClient(original) })

		ddb.SetClient(ddb.NewMock().WithTable(testTable, types.TableStatusActive))

		out, err := Handler(ctx, Input{TableName: testTable, Mode: ModeDescribe})
		Expect(err).NotTo(HaveOccurred())
		Expect(out.IsActive).To(BeTrue())
	})
})

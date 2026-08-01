package main

import (
	"context"
	"errors"
	"slices"
	"strings"

	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"

	"github.com/espressif/esp-cloud-common/go/aws_services/ddb"
	"github.com/espressif/esp-cloud-common/go/clog"
	"github.com/espressif/esp-cloud-common/go/util"
)

type Mode string

const (
	ModeDescribe Mode = "describe"
	ModeApply    Mode = "apply"
)

type Input struct {
	TableName            string                            `json:"table_name"`
	Operation            *types.GlobalSecondaryIndexUpdate `json:"operation,omitempty"`
	AttributeDefinitions []types.AttributeDefinition       `json:"attribute_definitions,omitempty"`
	Mode                 Mode                              `json:"mode"`
	Attempt              int                               `json:"attempt"`
}

type Output struct {
	IsActive bool `json:"is_active"`
	Attempt  int  `json:"attempt"`
}

func Handler(ctx context.Context, in Input) (Output, error) {
	return run(ctx, ddb.GetClient(), in)
}

func run(ctx context.Context, client ddb.ControlPlaneClient, in Input) (Output, error) {
	clog.Info().Str("table", in.TableName).Str("mode", string(in.Mode)).Int("attempt", in.Attempt).Msg("worker invoked")

	out, err := client.DescribeTable(ctx, &dynamodb.DescribeTableInput{TableName: aws.String(in.TableName)})
	if err != nil {
		clog.Error().Err(err).Str("table", in.TableName).Msg("DescribeTable failed")
		return Output{}, util.NewCustomError(err, "describe table "+in.TableName)
	}
	tbl := out.Table

	if in.Mode == ModeDescribe {
		return Output{IsActive: tbl.TableStatus == types.TableStatusActive, Attempt: in.Attempt}, nil
	}
	if tbl.TableStatus != types.TableStatusActive {
		// Table not ACTIVE — DDB rejects UpdateTable. Loop back so the SFN
		// waits and re-describes; can't fire-and-forget without ever calling
		// UpdateTable.
		return Output{Attempt: in.Attempt + 1}, nil
	}

	if in.Operation == nil {
		return Output{}, util.NewCustomError(errors.New("operation is required"), "worker apply mode")
	}
	switch {
	case in.Operation.Create != nil:
		return applyCreate(ctx, client, in, tbl)
	case in.Operation.Delete != nil:
		return applyDelete(ctx, client, in, tbl)
	default:
		return Output{}, util.NewCustomError(errors.New("operation must specify Create or Delete"), "worker apply mode")
	}
}

func applyCreate(ctx context.Context, client ddb.ControlPlaneClient, in Input, tbl *types.TableDescription) (Output, error) {
	want := in.Operation.Create
	name := aws.ToString(want.IndexName)

	existing := findGSI(tbl.GlobalSecondaryIndexes, name)
	if existing != nil {
		if existing.IndexStatus == types.IndexStatusDeleting {
			// A prior drift-recreate Delete is still in flight. Must wait
			// for it to finish before issuing the Create — DDB rejects
			// creating an index while one with the same name is DELETING.
			return Output{Attempt: in.Attempt + 1}, nil
		}
		if !gsiMatches(*existing, *want) {
			clog.Info().Str("table", in.TableName).Str("index", name).Msg("schema drift; deleting GSI for recreate")
			_, err := client.UpdateTable(ctx, &dynamodb.UpdateTableInput{
				TableName: aws.String(in.TableName),
				GlobalSecondaryIndexUpdates: []types.GlobalSecondaryIndexUpdate{{
					Delete: &types.DeleteGlobalSecondaryIndexAction{IndexName: aws.String(name)},
				}},
			})
			if err != nil {
				return handleUpdateErr(in, "delete", name, err)
			}
			return Output{Attempt: in.Attempt + 1}, nil
		}
		// Schema matches — even if it's still CREATING, treat as done.
		// CFN gets success; DDB finishes provisioning on its own.
		return Output{IsActive: true, Attempt: in.Attempt}, nil
	}

	_, err := client.UpdateTable(ctx, &dynamodb.UpdateTableInput{
		TableName:                   aws.String(in.TableName),
		AttributeDefinitions:        mergeAttrDefs(tbl.AttributeDefinitions, in.AttributeDefinitions),
		GlobalSecondaryIndexUpdates: []types.GlobalSecondaryIndexUpdate{{Create: want}},
	})
	if err != nil {
		return handleUpdateErr(in, "create", name, err)
	}
	// Fire-and-forget: UpdateTable accepted, GSI will reach ACTIVE in DDB's
	// own time. CFN sees success now, not after IndexStatus=ACTIVE. Callers
	// that read the GSI immediately may get errors until DDB finishes.
	return Output{IsActive: true, Attempt: in.Attempt}, nil
}

func applyDelete(ctx context.Context, client ddb.ControlPlaneClient, in Input, tbl *types.TableDescription) (Output, error) {
	name := aws.ToString(in.Operation.Delete.IndexName)

	if findGSI(tbl.GlobalSecondaryIndexes, name) == nil {
		return Output{IsActive: true, Attempt: in.Attempt}, nil
	}

	_, err := client.UpdateTable(ctx, &dynamodb.UpdateTableInput{
		TableName:                   aws.String(in.TableName),
		GlobalSecondaryIndexUpdates: []types.GlobalSecondaryIndexUpdate{{Delete: in.Operation.Delete}},
	})
	if err != nil {
		return handleUpdateErr(in, "delete", name, err)
	}
	return Output{IsActive: true, Attempt: in.Attempt}, nil
}

func handleUpdateErr(in Input, op, name string, err error) (Output, error) {
	var riu *types.ResourceInUseException
	var lee *types.LimitExceededException
	if errors.As(err, &riu) || errors.As(err, &lee) {
		// UpdateTable rejected because the table is busy. Two distinct DDB
		// errors land here: ResourceInUseException (table not ACTIVE) and
		// LimitExceededException ("Only 1 online index can be created or
		// deleted simultaneously per table") — the latter surfaces under
		// fire-and-forget when CFN issues the next op while DDB is still
		// building a prior index. Both retry the same way.
		clog.Info().Str("table", in.TableName).Str("index", name).Msg("table busy, will retry")
		return Output{Attempt: in.Attempt + 1}, nil
	}
	msg := err.Error()
	if (op == "create" && strings.Contains(msg, "already exists")) ||
		(op == "delete" && strings.Contains(msg, "does not exist")) {
		clog.Info().Str("index", name).Str("op", op).Msg("UpdateTable race resolved")
		return Output{IsActive: true, Attempt: in.Attempt}, nil
	}
	clog.Error().Err(err).Str("table", in.TableName).Str("index", name).Str("op", op).Msg("UpdateTable failed")
	return Output{}, util.NewCustomError(err, "update table "+op+" "+name)
}

func findGSI(gsis []types.GlobalSecondaryIndexDescription, name string) *types.GlobalSecondaryIndexDescription {
	i := slices.IndexFunc(gsis, func(g types.GlobalSecondaryIndexDescription) bool {
		return aws.ToString(g.IndexName) == name
	})
	if i < 0 {
		return nil
	}
	return &gsis[i]
}

// AWS doesn't preserve order on KeySchema or NonKeyAttributes, so both are
// compared as sets. ProvisionedThroughput is skipped (PAY_PER_REQUEST).
func gsiMatches(existing types.GlobalSecondaryIndexDescription, want types.CreateGlobalSecondaryIndexAction) bool {
	if aws.ToString(existing.IndexName) != aws.ToString(want.IndexName) {
		return false
	}
	if !sameKeySchema(existing.KeySchema, want.KeySchema) {
		return false
	}
	return sameProjection(existing.Projection, want.Projection)
}

func sameKeySchema(a, b []types.KeySchemaElement) bool {
	if len(a) != len(b) {
		return false
	}
	keyOf := func(k types.KeySchemaElement) string {
		return aws.ToString(k.AttributeName) + "/" + string(k.KeyType)
	}
	as := make([]string, len(a))
	bs := make([]string, len(b))
	for i := range a {
		as[i] = keyOf(a[i])
	}
	for i := range b {
		bs[i] = keyOf(b[i])
	}
	slices.Sort(as)
	slices.Sort(bs)
	return slices.Equal(as, bs)
}

func sameProjection(a, b *types.Projection) bool {
	if a == nil || b == nil {
		return a == b
	}
	if a.ProjectionType != b.ProjectionType {
		return false
	}
	an := append([]string(nil), a.NonKeyAttributes...)
	bn := append([]string(nil), b.NonKeyAttributes...)
	slices.Sort(an)
	slices.Sort(bn)
	return slices.Equal(an, bn)
}

func mergeAttrDefs(existing []types.AttributeDefinition, additions []types.AttributeDefinition) []types.AttributeDefinition {
	out := append([]types.AttributeDefinition(nil), existing...)
	seen := map[string]bool{}
	for _, a := range out {
		seen[aws.ToString(a.AttributeName)] = true
	}
	for _, a := range additions {
		if !seen[aws.ToString(a.AttributeName)] {
			out = append(out, a)
			seen[aws.ToString(a.AttributeName)] = true
		}
	}
	return out
}

func main() {
	lambda.Start(Handler)
}

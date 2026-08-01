package gsi_infra

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/aws/aws-lambda-go/cfn"
	"github.com/aws/aws-sdk-go-v2/aws"
	ddbtypes "github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
	sfntypes "github.com/aws/aws-sdk-go-v2/service/sfn/types"
	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"

	"github.com/espressif/esp-cloud-common/go/aws_services/sfn"
)

func TestGsiTrigger(t *testing.T) {
	RegisterFailHandler(Fail)
	RunSpecs(t, "GSI Trigger Suite")
}

func event(reqType cfn.RequestType, props *GsiResourceProperties, physicalID string) json.RawMessage {
	return eventWithData(reqType, props, physicalID, nil)
}

func eventWithData(reqType cfn.RequestType, props *GsiResourceProperties, physicalID string, data map[string]interface{}) json.RawMessage {
	rawProps := map[string]interface{}{}
	if props != nil {
		b, _ := json.Marshal(props)
		_ = json.Unmarshal(b, &rawProps)
	}
	ev := cfn.Event{
		RequestType:        reqType,
		PhysicalResourceID: physicalID,
		ResourceProperties: rawProps,
	}
	b, _ := json.Marshal(ev)
	if data == nil {
		return b
	}
	envelope := map[string]interface{}{}
	_ = json.Unmarshal(b, &envelope)
	envelope["Data"] = data
	out, _ := json.Marshal(envelope)
	return out
}

func basicProps() *GsiResourceProperties {
	return &GsiResourceProperties{
		StateMachineArn: "arn:sm:1",
		TableName:       "t",
		Operation: ddbtypes.GlobalSecondaryIndexUpdate{
			Create: &ddbtypes.CreateGlobalSecondaryIndexAction{IndexName: aws.String("idx_alpha")},
		},
	}
}

var _ = Describe("OnEvent", func() {
	var (
		ctx     context.Context
		sfnMock *sfn.Mock
	)

	BeforeEach(func() {
		ctx = context.Background()
		sfnMock = sfn.NewMock()
		sfn.SetClient(sfnMock)
	})

	Describe("CREATE / UPDATE (T-01, T-02)", func() {
		It("CREATE starts execution; PhysicalResourceId is stable, executionArn flows via Data", func() {
			sfnMock.NextExecutionArn = "arn:exec:1"
			out, err := OnEvent(ctx, event(cfn.RequestCreate, basicProps(), ""))
			Expect(err).NotTo(HaveOccurred())
			Expect(out.PhysicalResourceId).To(Equal("gsi:t:idx_alpha"))
			Expect(out.Data.ExecutionArn).To(Equal("arn:exec:1"))
			started := sfnMock.GetExecution("arn:exec:1")
			Expect(started).NotTo(BeNil())
			Expect(started.StateMachineArn).To(Equal("arn:sm:1"))
			Expect(started.Input).To(ContainSubstring(`"table_name":"t"`))
			Expect(started.Input).To(ContainSubstring(`"Create"`))
		})

		It("UPDATE keeps the same PhysicalResourceId and does not stop the prior execution", func() {
			sfnMock.WithExecution("arn:exec:old", sfntypes.ExecutionStatusRunning, "")
			sfnMock.NextExecutionArn = "arn:exec:upd"
			out, err := OnEvent(ctx, eventWithData(cfn.RequestUpdate, basicProps(), "gsi:t:idx_alpha", map[string]interface{}{"ExecutionArn": "arn:exec:old"}))
			Expect(err).NotTo(HaveOccurred())
			Expect(sfnMock.GetExecution("arn:exec:old").Status).To(Equal(sfntypes.ExecutionStatusRunning))
			Expect(out.PhysicalResourceId).To(Equal("gsi:t:idx_alpha"))
			Expect(out.Data.ExecutionArn).To(Equal("arn:exec:upd"))
			Expect(sfnMock.HasExecution("arn:exec:upd")).To(BeTrue())
		})

		It("rejects when StateMachineArn is missing", func() {
			props := basicProps()
			props.StateMachineArn = ""
			_, err := OnEvent(ctx, event(cfn.RequestCreate, props, ""))
			Expect(err).To(HaveOccurred())
		})

		It("rejects when TableName is missing", func() {
			props := basicProps()
			props.TableName = ""
			_, err := OnEvent(ctx, event(cfn.RequestCreate, props, ""))
			Expect(err).To(HaveOccurred())
		})

		It("propagates StartExecution errors (T-09)", func() {
			sfnMock.NextStartError = errors.New("ExecutionLimitExceeded")
			_, err := OnEvent(ctx, event(cfn.RequestCreate, basicProps(), ""))
			Expect(err).To(HaveOccurred())
		})

		It("names the create execution with the correlatable prefix", func() {
			sfnMock.NextExecutionArn = "arn:exec:named"
			out, err := OnEvent(ctx, event(cfn.RequestCreate, basicProps(), ""))
			Expect(err).NotTo(HaveOccurred())
			Expect(out.Data.ExecutionArn).To(Equal("arn:exec:named"))
			arns := sfnMock.Executions()
			Expect(arns).To(HaveLen(1))
			started := sfnMock.GetExecution(arns[0])
			Expect(started).NotTo(BeNil())
			Expect(started.Name).To(HavePrefix(GSICreateExecutionPrefix("t", "idx_alpha")))
		})

		It("rejects unknown RequestType", func() {
			_, err := OnEvent(ctx, event(cfn.RequestType("FrobnicateAll"), basicProps(), ""))
			Expect(err).To(HaveOccurred())
			Expect(err.Error()).To(ContainSubstring("OnEvent"))
		})
	})

	Describe("DELETE (T-03)", func() {
		It("stops prior execution (from event Data) then starts a Delete execution; PhysicalResourceId echoes the inbound ID", func() {
			sfnMock.WithExecution("arn:exec:prior", sfntypes.ExecutionStatusRunning, "")
			sfnMock.NextExecutionArn = "arn:exec:del"
			inboundID := "legacy-cfn-generated-id-XYZ"
			out, err := OnEvent(ctx, eventWithData(cfn.RequestDelete, basicProps(), inboundID, map[string]interface{}{"ExecutionArn": "arn:exec:prior"}))
			Expect(err).NotTo(HaveOccurred())
			Expect(out.PhysicalResourceId).To(Equal(inboundID))
			Expect(out.Data.ExecutionArn).To(Equal("arn:exec:del"))
			Expect(sfnMock.GetExecution("arn:exec:prior").Status).To(Equal(sfntypes.ExecutionStatusAborted))

			started := sfnMock.GetExecution("arn:exec:del")
			Expect(started).NotTo(BeNil())
			Expect(started.Input).To(ContainSubstring(`"Delete"`))
			Expect(started.Input).To(ContainSubstring(`"IndexName":"idx_alpha"`))
			Expect(started.Input).To(ContainSubstring(`"table_name":"t"`))
		})

		It("does not require a prior execution arn in Data", func() {
			sfnMock.NextExecutionArn = "arn:exec:del"
			out, err := OnEvent(ctx, event(cfn.RequestDelete, basicProps(), "gsi:t:idx_alpha"))
			Expect(err).NotTo(HaveOccurred())
			Expect(out.PhysicalResourceId).To(Equal("gsi:t:idx_alpha"))
			Expect(sfnMock.Executions()).To(ConsistOf("arn:exec:del"))
		})

		It("echoes a CFN-generated PhysicalResourceId on Delete (recovers stacks created before the stable-ID format)", func() {
			sfnMock.NextExecutionArn = "arn:exec:del"
			legacyID := "gsi-infra-itest-ExampleTableGsiIndexidxa43EE6154-1T22BYISKS10I"
			out, err := OnEvent(ctx, event(cfn.RequestDelete, basicProps(), legacyID))
			Expect(err).NotTo(HaveOccurred())
			Expect(out.PhysicalResourceId).To(Equal(legacyID))
		})

		It("rejects a Delete event missing the Operation.Create.IndexName", func() {
			props := &GsiResourceProperties{
				StateMachineArn: "arn:sm:1",
				TableName:       "t",
				Operation:       ddbtypes.GlobalSecondaryIndexUpdate{Create: &ddbtypes.CreateGlobalSecondaryIndexAction{}}, // no IndexName
			}
			_, err := OnEvent(ctx, event(cfn.RequestDelete, props, ""))
			Expect(err).To(HaveOccurred())
			Expect(sfnMock.Executions()).To(BeEmpty())
		})
	})
})

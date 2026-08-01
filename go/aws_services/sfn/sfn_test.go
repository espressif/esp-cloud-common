package sfn

import (
	"context"
	"errors"

	sfntypes "github.com/aws/aws-sdk-go-v2/service/sfn/types"
	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

var _ = Describe("ListExecutions + StartExecutionNamed", func() {
	var m *Mock
	BeforeEach(func() { m = NewMock(); SetClient(m) })

	It("lists executions for a state machine newest-first", func() {
		m.WithExecutionFull("arn:sm:orch", "g-aaa-c-1", "arn:exec:1", sfntypes.ExecutionStatusSucceeded, "")
		m.WithExecutionFull("arn:sm:orch", "g-aaa-c-2", "arn:exec:2", sfntypes.ExecutionStatusFailed, "bad schema")
		out, err := ListExecutions(context.Background(), "arn:sm:orch", 100)
		Expect(err).NotTo(HaveOccurred())
		Expect(out).To(HaveLen(2))
		Expect(out[0].Name).To(Equal("g-aaa-c-2")) // newest first
		Expect(out[0].Status).To(Equal(sfntypes.ExecutionStatusFailed))
	})

	It("only returns executions for the requested state machine", func() {
		m.WithExecutionFull("arn:sm:orch", "g-aaa-c-1", "arn:exec:1", sfntypes.ExecutionStatusRunning, "")
		m.WithExecutionFull("arn:sm:other", "g-bbb-c-1", "arn:exec:2", sfntypes.ExecutionStatusRunning, "")
		out, err := ListExecutions(context.Background(), "arn:sm:orch", 100)
		Expect(err).NotTo(HaveOccurred())
		Expect(out).To(HaveLen(1))
		Expect(out[0].Arn).To(Equal("arn:exec:1"))
	})

	It("StartExecutionNamed records the name", func() {
		arn, err := StartExecutionNamed(context.Background(), "arn:sm:orch", "{}", "g-aaa-c-xyz")
		Expect(err).NotTo(HaveOccurred())
		Expect(m.GetExecution(arn).Name).To(Equal("g-aaa-c-xyz"))
	})

	It("ListExecutions surfaces a seeded error", func() {
		m.NextListError = errors.New("throttled")
		_, err := ListExecutions(context.Background(), "arn:sm:orch", 100)
		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("throttled"))

		// cleared after use
		out, err := ListExecutions(context.Background(), "arn:sm:orch", 100)
		Expect(err).NotTo(HaveOccurred())
		Expect(out).To(BeEmpty())
	})
})

package gsi_infra

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	ddbtypes "github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
	sfntypes "github.com/aws/aws-sdk-go-v2/service/sfn/types"
	"github.com/aws/smithy-go"
	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"

	cc_ddb "github.com/espressif/esp-cloud-common/go/aws_services/ddb"
	ccsfn "github.com/espressif/esp-cloud-common/go/aws_services/sfn"
)

// roundTripFunc lets a test stand in for http.Client's transport.
type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

var _ = Describe("ReadinessCheck", func() {
	var (
		ddb     *cc_ddb.Mock
		origCli cc_ddb.ControlPlaneClient
		sfnMock *ccsfn.Mock
		origSfn ccsfn.Client
	)

	BeforeEach(func() {
		ddb = cc_ddb.NewMock()
		origCli = cc_ddb.GetClient()
		cc_ddb.SetClient(ddb)

		sfnMock = ccsfn.NewMock()
		origSfn = ccsfn.GetClient()
		ccsfn.SetClient(sfnMock)
		os.Setenv("GSI_ORCHESTRATOR_STATE_MACHINE_ARN", "arn:sm:orch")
	})
	AfterEach(func() {
		cc_ddb.SetClient(origCli)
		ccsfn.SetClient(origSfn)
		os.Unsetenv("GSI_ORCHESTRATOR_STATE_MACHINE_ARN")
	})

	check := func(expected map[string][]string) json.RawMessage {
		b, _ := json.Marshal(ReadinessCheckRequest{Expected: expected})
		return b
	}

	It("Ready=true when every expected GSI is present and ACTIVE", func() {
		ddb.WithTable("a", ddbtypes.TableStatusActive).
			WithGSI("a", "idx_a", "k", "", ddbtypes.IndexStatusActive)
		ddb.WithTable("b", ddbtypes.TableStatusActive)

		out, err := ReadinessCheck(context.Background(), check(map[string][]string{"a": {"idx_a"}, "b": {}}))
		Expect(err).NotTo(HaveOccurred())
		Expect(out.Ready).To(BeTrue())
	})

	It("Ready=false when an EXPECTED GSI is absent (not yet created)", func() {
		// The critical fire-and-forget case: the table is ACTIVE but the expected
		// GSI has not been created yet — must NOT report ready.
		ddb.WithTable("a", ddbtypes.TableStatusActive)

		out, err := ReadinessCheck(context.Background(), check(map[string][]string{"a": {"idx_a"}}))
		Expect(err).NotTo(HaveOccurred())
		Expect(out.Ready).To(BeFalse())
	})

	It("Ready=false when an expected GSI is still CREATING", func() {
		ddb.WithTable("a", ddbtypes.TableStatusActive).
			WithGSI("a", "idx_a", "k", "", ddbtypes.IndexStatusCreating)

		out, err := ReadinessCheck(context.Background(), check(map[string][]string{"a": {"idx_a"}}))
		Expect(err).NotTo(HaveOccurred())
		Expect(out.Ready).To(BeFalse())
	})

	It("Ready=false when an expected GSI is ACTIVE but Backfilling", func() {
		ddb.WithTable("a", ddbtypes.TableStatusActive).
			WithGSIDescription("a", ddbtypes.GlobalSecondaryIndexDescription{
				IndexName:   aws.String("idx_a"),
				IndexStatus: ddbtypes.IndexStatusActive,
				Backfilling: aws.Bool(true),
			})

		out, err := ReadinessCheck(context.Background(), check(map[string][]string{"a": {"idx_a"}}))
		Expect(err).NotTo(HaveOccurred())
		Expect(out.Ready).To(BeFalse())
	})

	It("Ready=false when the table itself is not ACTIVE", func() {
		ddb.WithTable("a", ddbtypes.TableStatusUpdating).
			WithGSI("a", "idx_a", "k", "", ddbtypes.IndexStatusActive)

		out, err := ReadinessCheck(context.Background(), check(map[string][]string{"a": {"idx_a"}}))
		Expect(err).NotTo(HaveOccurred())
		Expect(out.Ready).To(BeFalse())
	})

	It("Ready=true for a table with no expected GSIs once ACTIVE", func() {
		ddb.WithTable("solo", ddbtypes.TableStatusActive)
		out, err := ReadinessCheck(context.Background(), check(map[string][]string{"solo": {}}))
		Expect(err).NotTo(HaveOccurred())
		Expect(out.Ready).To(BeTrue())
	})

	It("treats a missing table as not-ready (keeps polling), not an error", func() {
		ddb.NextDescribeError = &ddbtypes.ResourceNotFoundException{Message: aws.String("no table")}
		out, err := ReadinessCheck(context.Background(), check(map[string][]string{"a": {"idx_a"}}))
		Expect(err).NotTo(HaveOccurred())
		Expect(out.Ready).To(BeFalse())
	})

	It("errors on an empty expected set", func() {
		_, err := ReadinessCheck(context.Background(), check(map[string][]string{}))
		Expect(err).To(HaveOccurred())
	})

	It("errors on undecodable input", func() {
		_, err := ReadinessCheck(context.Background(), json.RawMessage(`{"expected": "not-a-map"}`))
		Expect(err).To(HaveOccurred())
	})

	It("propagates non-not-found DescribeTable errors", func() {
		ddb.WithTable("a", ddbtypes.TableStatusActive)
		ddb.NextDescribeError = errors.New("boom")
		_, err := ReadinessCheck(context.Background(), check(map[string][]string{"a": {}}))
		Expect(err).To(HaveOccurred())
	})

	It("Failed=true when an absent GSI's newest create execution FAILED", func() {
		ddb.WithTable("a", ddbtypes.TableStatusActive)
		sfnMock.WithExecutionFull("arn:sm:orch", GSICreateExecutionName("a", "idx_a"), "arn:exec:1",
			sfntypes.ExecutionStatusFailed, "ValidationException: bad KeySchema")
		out, err := ReadinessCheck(context.Background(), check(map[string][]string{"a": {"idx_a"}}))
		Expect(err).NotTo(HaveOccurred())
		Expect(out.Failed).To(BeTrue())
		Expect(out.Reason).To(ContainSubstring("idx_a"))
	})

	It("waiting (not failed) when the newest matching execution is RUNNING", func() {
		ddb.WithTable("a", ddbtypes.TableStatusActive)
		sfnMock.WithExecutionFull("arn:sm:orch", GSICreateExecutionName("a", "idx_a"), "arn:exec:1",
			sfntypes.ExecutionStatusRunning, "")
		out, err := ReadinessCheck(context.Background(), check(map[string][]string{"a": {"idx_a"}}))
		Expect(err).NotTo(HaveOccurred())
		Expect(out.Failed).To(BeFalse())
		Expect(out.Ready).To(BeFalse())
	})

	It("waiting when no matching execution exists yet", func() {
		ddb.WithTable("a", ddbtypes.TableStatusActive)
		out, err := ReadinessCheck(context.Background(), check(map[string][]string{"a": {"idx_a"}}))
		Expect(err).NotTo(HaveOccurred())
		Expect(out.Failed).To(BeFalse())
		Expect(out.Ready).To(BeFalse())
	})

	It("waiting when a stale FAILED execution is superseded by a newer RUNNING one", func() {
		ddb.WithTable("a", ddbtypes.TableStatusActive)
		prefix := GSICreateExecutionPrefix("a", "idx_a")
		sfnMock.WithExecutionFull("arn:sm:orch", prefix+"old", "arn:exec:old", sfntypes.ExecutionStatusFailed, "old fail")
		sfnMock.WithExecutionFull("arn:sm:orch", prefix+"new", "arn:exec:new", sfntypes.ExecutionStatusRunning, "")
		out, err := ReadinessCheck(context.Background(), check(map[string][]string{"a": {"idx_a"}}))
		Expect(err).NotTo(HaveOccurred())
		Expect(out.Failed).To(BeFalse())
	})

	It("escalates AccessDenied from the SFN lookup as an error", func() {
		ddb.WithTable("a", ddbtypes.TableStatusActive)
		sfnMock.NextListError = &smithy.GenericAPIError{Code: "AccessDeniedException", Message: "no perms"}
		_, err := ReadinessCheck(context.Background(), check(map[string][]string{"a": {"idx_a"}}))
		Expect(err).To(HaveOccurred())
	})

	It("treats a transient SFN lookup error as waiting, not failed", func() {
		ddb.WithTable("a", ddbtypes.TableStatusActive)
		sfnMock.NextListError = errors.New("throttled")
		out, err := ReadinessCheck(context.Background(), check(map[string][]string{"a": {"idx_a"}}))
		Expect(err).NotTo(HaveOccurred())
		Expect(out.Failed).To(BeFalse())
		Expect(out.Ready).To(BeFalse())
	})
})

var _ = Describe("ReadinessSignal", func() {
	var origClient *http.Client

	BeforeEach(func() {
		origClient = signalHTTPClient
	})
	AfterEach(func() {
		signalHTTPClient = origClient
	})

	signalReq := func(url, status string) json.RawMessage {
		b, _ := json.Marshal(ReadinessSignalRequest{SignalURL: url, Status: status})
		return b
	}

	It("PUTs the signal with NO Content-Type header (SigV2 requirement)", func() {
		var captured *http.Request
		var capturedBody string
		signalHTTPClient = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			captured = r
			b, _ := io.ReadAll(r.Body)
			capturedBody = string(b)
			return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(""))}, nil
		})}

		out, err := ReadinessSignal(context.Background(),
			signalReq("https://cfn-wait.s3.amazonaws.com/x?Expires=1&AWSAccessKeyId=k&Signature=s", "SUCCESS"))
		Expect(err).NotTo(HaveOccurred())
		Expect(out.Signaled).To(Equal("SUCCESS"))
		Expect(out.HTTPStatus).To(Equal(200))
		Expect(captured.Method).To(Equal(http.MethodPut))
		Expect(captured.Header.Get("Content-Type")).To(BeEmpty())
		Expect(capturedBody).To(ContainSubstring(`"Status":"SUCCESS"`))
		Expect(capturedBody).To(ContainSubstring(`"UniqueId":"gsi-readiness"`))
	})

	It("sends Status=FAILURE when asked", func() {
		var capturedBody string
		signalHTTPClient = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			b, _ := io.ReadAll(r.Body)
			capturedBody = string(b)
			return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(""))}, nil
		})}
		_, err := ReadinessSignal(context.Background(), signalReq("https://h/x?a=b", "FAILURE"))
		Expect(err).NotTo(HaveOccurred())
		Expect(capturedBody).To(ContainSubstring(`"Status":"FAILURE"`))
	})

	It("errors when signal_url is missing", func() {
		_, err := ReadinessSignal(context.Background(), signalReq("", "SUCCESS"))
		Expect(err).To(HaveOccurred())
	})

	It("errors on a non-2xx response", func() {
		signalHTTPClient = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			return &http.Response{StatusCode: 403, Body: io.NopCloser(strings.NewReader("SignatureDoesNotMatch"))}, nil
		})}
		_, err := ReadinessSignal(context.Background(), signalReq("https://h/x?a=b", "SUCCESS"))
		Expect(err).To(HaveOccurred())
	})

	It("propagates transport errors", func() {
		signalHTTPClient = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			return nil, errors.New("network down")
		})}
		_, err := ReadinessSignal(context.Background(), signalReq("https://h/x?a=b", "SUCCESS"))
		Expect(err).To(HaveOccurred())
	})
})

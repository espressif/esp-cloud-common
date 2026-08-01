// Package gsi_infra (continued) hosts the GsiReadinessGate Lambdas: a
// stack-level readiness barrier driven by a Step Functions state machine and
// gated by a native AWS::CloudFormation::WaitCondition (up to 12h) instead of a
// custom resource (bounded by CloudFormation's ~1h ServiceTimeout). The state
// machine loops ReadinessCheck until every table + GSI is ready, then invokes
// ReadinessSignal to release the WaitCondition. Wired via the [GsiReadinessGate]
// CDK construct.
package gsi_infra

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
	sfntypes "github.com/aws/aws-sdk-go-v2/service/sfn/types"
	"github.com/aws/smithy-go"

	ccsfn "github.com/espressif/esp-cloud-common/go/aws_services/sfn"

	cc_ddb "github.com/espressif/esp-cloud-common/go/aws_services/ddb"
	"github.com/espressif/esp-cloud-common/go/clog"
	"github.com/espressif/esp-cloud-common/go/util"
)

// ReadinessCheckRequest is the input to the readiness "check" step.
//
// Expected maps each managed table to the GSI index names that MUST exist and
// be ACTIVE before the stack is considered ready. A table with no GSIs maps to
// an empty list (only its TableStatus is checked).
//
// Passing the *expected* set — not just table names — is essential in
// fire-and-forget mode: a per-GSI custom resource returns as soon as the
// orchestrator execution is *started*, before the GSI is created, so checking
// only the GSIs currently present on the table could report ready while an
// expected GSI has not been built yet. Requiring every expected index to be
// present-and-ACTIVE closes that window (and surfaces a create that never lands
// as a never-ready condition rather than a silent success).
type ReadinessCheckRequest struct {
	Expected map[string][]string `json:"expected"`
}

// ReadinessCheckResponse reports whether every expected table and GSI is
// ready, or — if not — whether the cause is a terminally failed create.
//
// Failed and Reason are intentionally emitted without `omitempty`. The
// readiness state machine's Choice tests `$.check.failed` (so it must always
// be present, false included), and its SignalCreateFailed branch reads
// `$.check.reason` — a JSONPath that errors, and strands the execution until
// the WaitCondition timeout, if the field is ever absent on a failure. Always
// serializing Reason keeps that branch resolvable regardless of caller.
type ReadinessCheckResponse struct {
	Ready  bool   `json:"ready"`
	Failed bool   `json:"failed"`
	Reason string `json:"reason"`
}

// orchestratorArnEnv names the env var carrying the GSI orchestrator state
// machine's ARN. Empty/unset disables failure detection entirely — the check
// behaves exactly as it did before this feature existed.
const orchestratorArnEnv = "GSI_ORCHESTRATOR_STATE_MACHINE_ARN"

// maxReasonLen caps the Failed reason string (Step Functions state payloads
// have size limits, and Cause/error text from a describe-execution call is
// unbounded).
const maxReasonLen = 1000

// listScanLimit bounds how many recent orchestrator executions ReadinessCheck
// scans per (table, index) lookup.
const listScanLimit = 100

// ReadinessCheck runs one poll: is every expected table ACTIVE and every
// expected GSI present, ACTIVE, and no longer Backfilling? The readiness state
// machine calls this on a loop (Wait -> ReadinessCheck -> Choice) until it
// returns Ready=true or Failed=true.
//
// When an expected table/GSI is not yet ready, and GSI_ORCHESTRATOR_STATE_MACHINE_ARN
// is set, the check also consults the orchestrator state machine for that
// (table, index)'s most-recent CREATE execution: a terminal failure there
// means the GSI is never going to show up on its own, so we report Failed
// immediately instead of waiting out the full poll budget.
func ReadinessCheck(ctx context.Context, raw json.RawMessage) (ReadinessCheckResponse, error) {
	var req ReadinessCheckRequest
	if err := json.Unmarshal(raw, &req); err != nil {
		return ReadinessCheckResponse{}, util.NewCustomError(err, "decode readiness check request")
	}
	if len(req.Expected) == 0 {
		return ReadinessCheckResponse{}, util.NewCustomError(errors.New("expected set is empty"), "ReadinessCheck")
	}

	client := cc_ddb.GetClient()
	notReady := false
	for table, wantIndexes := range req.Expected {
		out, err := client.DescribeTable(ctx, &dynamodb.DescribeTableInput{TableName: aws.String(table)})
		if err != nil {
			var notFound *types.ResourceNotFoundException
			if errors.As(err, &notFound) {
				// Table not created yet — not ready, keep polling (don't fail).
				clog.Info().Str("table", table).Msg("table not found yet; not ready")
				notReady = true
				continue
			}
			return ReadinessCheckResponse{}, util.NewCustomError(err, "describe table "+table)
		}
		tbl := out.Table
		if tbl == nil || tbl.TableStatus != types.TableStatusActive {
			notReady = true
			continue
		}

		existing := make(map[string]types.GlobalSecondaryIndexDescription, len(tbl.GlobalSecondaryIndexes))
		for _, g := range tbl.GlobalSecondaryIndexes {
			existing[aws.ToString(g.IndexName)] = g
		}

		for _, want := range wantIndexes {
			g, ok := existing[want]
			if !ok || g.IndexStatus != types.IndexStatusActive || (g.Backfilling != nil && *g.Backfilling) {
				// An expected GSI is absent, not ACTIVE, or still backfilling —
				// keep waiting, unless its CREATE execution has terminally failed.
				clog.Info().Str("table", table).Str("index", want).Msg("expected GSI not ready")
				failed, reason, err := createExecutionFailure(ctx, table, want)
				if err != nil {
					return ReadinessCheckResponse{}, err // e.g. AccessDenied — escalate
				}
				if failed {
					return ReadinessCheckResponse{Failed: true, Reason: reason}, nil
				}
				notReady = true
				continue
			}
		}
	}
	return ReadinessCheckResponse{Ready: !notReady}, nil
}

// createExecutionFailure reports whether (table, index)'s most-recent CREATE
// orchestrator execution terminally failed. Executions are scanned
// newest-first, so a fixed redeploy's newer execution supersedes a stale
// failure. A transient SFN lookup error is swallowed (treated as
// "undetermined", i.e. keep waiting); an AccessDenied is returned as an error
// so a broken IAM setup surfaces fast instead of silently stalling forever.
func createExecutionFailure(ctx context.Context, table, index string) (bool, string, error) {
	arn := os.Getenv(orchestratorArnEnv)
	if arn == "" {
		return false, "", nil // detection disabled
	}
	prefix := GSICreateExecutionPrefix(table, index)
	execs, err := ccsfn.ListExecutions(ctx, arn, listScanLimit)
	if err != nil {
		var apiErr smithy.APIError
		if errors.As(err, &apiErr) && apiErr.ErrorCode() == "AccessDeniedException" {
			return false, "", util.NewCustomError(err, "list orchestrator executions")
		}
		clog.Warn().Err(err).Str("table", table).Str("index", index).Msg("orchestrator execution lookup failed; treating as not-ready")
		return false, "", nil
	}
	for _, e := range execs { // newest-first
		if !strings.HasPrefix(e.Name, prefix) {
			continue
		}
		switch e.Status {
		case sfntypes.ExecutionStatusFailed, sfntypes.ExecutionStatusTimedOut, sfntypes.ExecutionStatusAborted:
			_, cause, derr := ccsfn.DescribeExecution(ctx, e.Arn)
			if derr != nil {
				cause = "(cause unavailable)"
			}
			reason := fmt.Sprintf("%s/%s: execution %s %s: %s", table, index, e.Arn, e.Status, cause)
			if len(reason) > maxReasonLen {
				reason = reason[:maxReasonLen]
			}
			return true, reason, nil
		default:
			return false, "", nil // newest match is RUNNING/SUCCEEDED — not failed
		}
	}
	return false, "", nil // no matching execution yet
}

// ReadinessSignalRequest is the input to the readiness "signal" step.
type ReadinessSignalRequest struct {
	SignalURL string `json:"signal_url"`
	Status    string `json:"status"`
	Reason    string `json:"reason,omitempty"`
	UniqueID  string `json:"unique_id,omitempty"`
	Data      string `json:"data,omitempty"`
}

// ReadinessSignalResponse is returned after the signal PUT.
type ReadinessSignalResponse struct {
	Signaled   string `json:"signaled"`
	HTTPStatus int    `json:"http_status"`
}

// signalHTTPClient is the client used to PUT the WaitCondition signal.
// A package-level var so tests can inject a fake transport.
var signalHTTPClient = http.DefaultClient

// ReadinessSignal PUTs a SUCCESS/FAILURE signal to a CloudFormation
// WaitCondition pre-signed S3 URL. The state machine invokes it once — after
// ReadinessCheck reports ready, or from its failure Catch — so it never waits
// and Lambda's 15-min limit is irrelevant.
//
// The pre-signed URL is SigV2: the PUT must carry an empty/omitted Content-Type
// or S3 returns 403 SignatureDoesNotMatch. Go's http client does not set
// Content-Type unless asked, so we deliberately leave it unset.
func ReadinessSignal(ctx context.Context, raw json.RawMessage) (ReadinessSignalResponse, error) {
	var req ReadinessSignalRequest
	if err := json.Unmarshal(raw, &req); err != nil {
		return ReadinessSignalResponse{}, util.NewCustomError(err, "decode readiness signal request")
	}
	if req.SignalURL == "" {
		return ReadinessSignalResponse{}, util.NewCustomError(errors.New("signal_url is required"), "ReadinessSignal")
	}

	status := req.Status
	if status == "" {
		status = "SUCCESS"
	}
	uniqueID := req.UniqueID
	if uniqueID == "" {
		uniqueID = "gsi-readiness"
	}
	reason := req.Reason
	if reason == "" {
		if status == "SUCCESS" {
			reason = "GSIs ACTIVE"
		} else {
			reason = "GSI readiness failed"
		}
	}

	body, err := json.Marshal(map[string]string{
		"Status":   status,
		"UniqueId": uniqueID,
		"Reason":   reason,
		"Data":     req.Data,
	})
	if err != nil {
		return ReadinessSignalResponse{}, util.NewCustomError(err, "marshal signal body")
	}

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPut, req.SignalURL, bytes.NewReader(body))
	if err != nil {
		return ReadinessSignalResponse{}, util.NewCustomError(err, "build signal request")
	}
	// Intentionally NO Content-Type header (SigV2 signature requires it empty).

	resp, err := signalHTTPClient.Do(httpReq)
	if err != nil {
		return ReadinessSignalResponse{}, util.NewCustomError(err, "send wait-condition signal")
	}
	defer resp.Body.Close()
	respBody, _ := io.ReadAll(resp.Body)

	clog.Info().Str("status", status).Int("http_status", resp.StatusCode).Msg("wait-condition signal sent")
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return ReadinessSignalResponse{}, util.NewCustomError(
			fmt.Errorf("wait-condition signal failed: HTTP %d: %s", resp.StatusCode, string(respBody)),
			"ReadinessSignal",
		)
	}
	return ReadinessSignalResponse{Signaled: status, HTTPStatus: resp.StatusCode}, nil
}

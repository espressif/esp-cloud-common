package gsi_infra

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
)

func gsiHash16(table, index string) string {
	sum := sha256.Sum256([]byte(table + "/" + index))
	return hex.EncodeToString(sum[:])[:16]
}

func randHex(n int) string {
	b := make([]byte, n)
	// crypto/rand.Read only errors on catastrophic OS failure; ignore per stdlib guidance.
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// GSICreateExecutionPrefix is the deterministic name prefix shared by the
// producer (onEvent) and the consumer (readiness check) to identify a
// table/index's CREATE orchestrator executions.
func GSICreateExecutionPrefix(table, index string) string {
	return "g-" + gsiHash16(table, index) + "-c-"
}

// GSICreateExecutionName returns a unique execution name for a create op.
func GSICreateExecutionName(table, index string) string {
	return GSICreateExecutionPrefix(table, index) + randHex(8)
}

// GSIDeleteExecutionName returns a unique execution name for a delete op.
func GSIDeleteExecutionName(table, index string) string {
	return "g-" + gsiHash16(table, index) + "-d-" + randHex(8)
}

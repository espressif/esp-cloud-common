// SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
//
// SPDX-License-Identifier: Apache-2.0

package util

import "encoding/json"

// ConvertAnyToAny copies fields between source and ptrToTarget by way of
// JSON. It works for map↔struct, struct↔struct, and map↔map. Numbers in
// map targets are unmarshaled as float64. Fields not present in source
// are not zeroed in the target — the call merges into ptrToTarget rather
// than replacing it.
func ConvertAnyToAny(source any, ptrToTarget any) error {
	if source == nil || ptrToTarget == nil {
		return nil
	}
	b, err := json.Marshal(source)
	if err != nil {
		return err
	}
	return json.Unmarshal(b, ptrToTarget)
}

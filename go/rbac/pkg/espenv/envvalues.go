// SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
//
// SPDX-License-Identifier: Apache-2.0

package espenv

import (
	"os"
)

// These Environment variables need to exist in the Lambda environment.
const (
	LOG_LEVEL = "LOG_LEVEL"
)

func GetLogLevel() string {
	return os.Getenv(LOG_LEVEL)
}

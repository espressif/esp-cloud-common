// SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
//
// SPDX-License-Identifier: Apache-2.0

package main

import (
	"github.com/aws/aws-lambda-go/lambda"

	gsi "github.com/espressif/esp-cloud-common/cdk_go/gsi_infra/lambdas"
)

func main() {
	lambda.Start(gsi.ReadinessSignal)
}

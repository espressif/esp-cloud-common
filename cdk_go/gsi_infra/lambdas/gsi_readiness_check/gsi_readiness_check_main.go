package main

import (
	"github.com/aws/aws-lambda-go/lambda"

	gsi "github.com/espressif/esp-cloud-common/cdk_go/gsi_infra/lambdas"
)

func main() {
	lambda.Start(gsi.ReadinessCheck)
}

#!/bin/sh
# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

#
# This file can be run locally to test the code and is triggered on every push to the CI.
# Note this runs on a runner which supports vanilla sh but not bash.

EXIT=0
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

check_error() {
    if [ $? != "0" ]; then
        echo "Error $1"
        EXIT=1
    fi
}


# Style checks are done here
echo "Running style checks with golangci-lint"
golangci-lint run --timeout 10m0s
check_error "Running style checks with golangci-lint"

echo "Running Unit tests"
go test ./... -coverprofile coverage.out -covermode count
go get github.com/boumenot/gocover-cobertura
go run github.com/boumenot/gocover-cobertura < coverage.out > coverage.xml
check_error "Running Unit tests"

echo "Running Dependency Check"
go list -buildvcs=false -json -deps ./... | nancy sleuth
check_error "Running Dependency Check"

if [ $EXIT -eq 1 ]; then
    echo "Status:${RED}Failure.${NC}"
    exit 1
fi

echo "Status:${BLUE}Success.${NC}"
exit 0

# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

# esp-cloud-common: shared infrastructure consumed via git submodule.
#
# Targets:
#   make setup      One-time per AWS account/region: bootstrap CDK so
#                   `cdk deploy` can stage Lambda assets to S3.
#   make test       Go unit tests under cdk_go/ and go/ (no AWS).
#   make go_build   Build all Lambda Go binaries into ./build/<name>/.
#   make itest      Python integration tests under cdk_go/**/itests/. Each
#                   fixture stack is self-contained (brings its own
#                   GsiInfraCore) and is created/destroyed via `cdk
#                   deploy` / `cdk destroy`. Set RUN_GSI_INFRA_ITEST=true
#                   to opt in; AWS credentials + a writable region are
#                   required. Depends on go_build.

# Discover Lambda main files anywhere under cdk_go/.
MAIN_FILES := $(shell find cdk_go -type f -name '*_main.go')
BINARY_NAME := bootstrap
BUILD_TARGETS := $(foreach m,$(MAIN_FILES),build/$(notdir $(patsubst %_main.go,%,$(m)))/$(BINARY_NAME))

# Hardcoded CDK bootstrap qualifier for esp-cloud-common integration
# tests. The synthesizer in cdk_go/gsi_infra/itests/example_stack/app.py
# uses the same string, so `make setup` and `make itest` agree on which
# CDK bootstrap S3 bucket / IAM roles to use without any env-var glue.
QUALIFIER := cc-itest

.PHONY: setup test go_build itest

setup:
	@echo "→ cdk bootstrap with qualifier=$(QUALIFIER)"
	@account=$$(aws sts get-caller-identity --query Account --output text); \
	region=$${AWS_REGION:-$$(aws configure get region)}; \
	cdk bootstrap --qualifier $(QUALIFIER) aws://$$account/$$region

TEST_ARGS ?=
TEST_PACKAGES := ./cdk_go/... ./go/...
COVERPKG := $(shell echo "$(TEST_PACKAGES)" | tr ' ' ',')

test:
	# Scope to ./cdk_go/... and ./go/... so the venv (./myenv) is skipped.
	# CDK init templates inside aws_cdk_cli ship intentionally-broken Go
	# files (%name%.template.go) that confuse `go build ./...`.
	@mkdir -p build/tests
	@rm -f build/tests/*.txt
	@go clean -testcache && \
		TEST_OUTPUT_DIR=$(CURDIR)/build/tests \
		ginkgo $(TEST_ARGS) --coverpkg=$(COVERPKG) --coverprofile=coverage.out $(TEST_PACKAGES)

# --- Vulnerability scanning (govulncheck) ---
# Same scope as TEST_PACKAGES (./cdk_go/... ./go/...) on purpose: `./...` pulls in
# the venv (./myenv) and the intentionally-broken CDK init templates under
# aws_cdk_cli (%name%.template.go) that fail to load. Blocking gate — the recipe
# exits non-zero if any reachable vulnerability is found or the scan errors.
GOVULNCHECK_VERSION ?= latest
GOPATH_BIN := $(shell go env GOPATH)/bin
VULNCHECK_PACKAGES := ./cdk_go/... ./go/...

.PHONY: vulncheck
vulncheck:
	@command -v govulncheck >/dev/null 2>&1 || go install golang.org/x/vuln/cmd/govulncheck@$(GOVULNCHECK_VERSION)
	@export PATH="$(GOPATH_BIN):$$PATH"; govulncheck $(VULNCHECK_PACKAGES)

go_build: $(BUILD_TARGETS)

# One rule per main file. Each builds the Linux/ARM64 Lambda binary into
# ./build/<name>/bootstrap so create_lambda_function can asset-load it.
define build_lambda
build/$(notdir $(patsubst %_main.go,%,$(1)))/$(BINARY_NAME): $(1)
	@mkdir -p $$(@D)
	GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -ldflags "-s -w" -tags lambda.norpc -trimpath -o $$@ $$<
endef
$(foreach m,$(MAIN_FILES),$(eval $(call build_lambda,$(m))))

itest: go_build
	RUN_GSI_INFRA_ITEST=true pytest cdk_go/gsi_infra/itests/ -v -s

.PHONY: clean
clean:
	rm -rf build/
	rm -rf cdk.out/

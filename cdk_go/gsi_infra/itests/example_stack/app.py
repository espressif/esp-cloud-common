#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Standalone CDK app for the GSI orchestrator integration-test fixture.

Synthesizes a single gsi-infra-itest stack with a ManagedTable, the
GsiInfra orchestrator, and a set of GSIs determined by
GSI_INFRA_SCENARIO. The stack is self-contained.

Usage (typically called from the integration test):
    cdk synth --app "python3 cdk_go/gsi_infra/itests/example_stack/app.py" \\
              --output <cdk-out-dir>
"""
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent          # itests/example_stack/
CDK_ROOT = HERE.parents[2]                      # esp-cloud-common/cdk_go/
sys.path.insert(0, str(CDK_ROOT))
sys.path.insert(0, str(HERE))

import aws_cdk as cdk

from stack import GsiInfraExampleStack, scenario_from_env

app = cdk.App()

# Bootstrap qualifier matches the one in Makefile's `setup` target so
# `cdk deploy` finds the assets bucket / IAM roles `make setup` created.
QUALIFIER = "cc-itest"
synthesizer = cdk.DefaultStackSynthesizer(
    qualifier=QUALIFIER,
    file_assets_bucket_name=f"cdk-{QUALIFIER}-assets-${{AWS::AccountId}}-${{AWS::Region}}",
)

GsiInfraExampleStack(
    app,
    "gsi-infra-itest",
    scenario=scenario_from_env(),
    synthesizer=synthesizer,
    description="GSI orchestrator integration-test fixture stack",
)

app.synth()

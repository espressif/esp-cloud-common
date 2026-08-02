// SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
//
// SPDX-License-Identifier: Apache-2.0

package rbac_test

import (
	"github.com/espressif/esp-cloud-common/go/rbac/pkg/testutils"
	"github.com/espressif/esp-cloud-common/go/rbac/rbac"
	"fmt"
	"log"
	"testing"

	"github.com/franela/goblin"
	"github.com/maxatome/go-testdeep/td"
)

const RoleMergeTestFile = "test/rolemerge_testcases.json"

type RoleMergeTestCases struct {
	Name  string
	Cases []RoleMergeTestCase
}

type RoleMergeTestCase struct {
	Description string
	Input       RoleMergeTestCaseInput
	Output      rbac.EntityPermissions
}
type RoleMergeTestCaseInput struct {
	Policies []rbac.Policy
}

func TestRoleMerge(t *testing.T) {
	var payload []RoleMergeTestCases
	// Read the test file
	err := testutils.ReadJsonFile(RoleMergeTestFile, &payload)
	if err != nil {
		log.Fatal("Error during Unmarshal: ", err)
	}

	g := goblin.Goblin(t)
	for _, testCases := range payload {
		for _, testCase := range testCases.Cases {
			fmt.Printf("testCase.Input.Policies: %v\n", testCase.Input.Policies)
			res := rbac.MergePolicies(testCase.Input.Policies)
			g.Describe(testCases.Name, func() {
				g.It(testCase.Description+" - Output Validation", func() {
					g.Assert(td.Cmp(t, res, testCase.Output)).Eql(true)
				})
			})
		}
	}
}

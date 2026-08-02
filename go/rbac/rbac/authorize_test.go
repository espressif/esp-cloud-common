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
)

const AuthorizeEntityTestFile = "test/authorize_testcases.json"

type AuthorizeEntityTestCases struct {
	Name  string
	Cases []AuthorizeEntityTestCase
}

type AuthorizeEntityTestCase struct {
	Description string
	Input       rbac.EntityPermissions
	ToValidate  []AuthorizeEntityCasesToValidate
}
type AuthorizeEntityCasesToValidate struct {
	Action   string `json:"action"`
	Resource string `json:"resource"`
	Expected bool   `json:"expected"`
}

func TestAuthorizeEntity(t *testing.T) {

	var payload []AuthorizeEntityTestCases
	// Read the test file
	err := testutils.ReadJsonFile(AuthorizeEntityTestFile, &payload)
	if err != nil {
		log.Fatal("Error during Unmarshal: ", err)
	}

	g := goblin.Goblin(t)
	for _, testCases := range payload {
		for _, testCase := range testCases.Cases {
			for i, toValidate := range testCase.ToValidate {
				res := testCase.Input.IsAuthorized(toValidate.Action, toValidate.Resource)
				g.Describe(testCases.Name, func() {
					g.It(fmt.Sprintf("%s - %d - Output Validation", testCase.Description, i+1), func() {
						g.Assert(res).Eql(toValidate.Expected)
					})
				})
			}
		}
	}
}

func TestEntitySetAllow(t *testing.T) {
	g := goblin.Goblin(t)

	var testIn rbac.EntityPermissions

	testIn.SetAllow("batch:get", "*")

	testMatch := rbac.EntityPermissions{"batch:get": map[string]rbac.Permission{"*": rbac.Permission{true}}}

	g.Describe("Test EntityPermissions for allow", func() {
		g.It("Output Validation", func() {
			g.Assert(testIn).Eql(testMatch)
		})
	})
}

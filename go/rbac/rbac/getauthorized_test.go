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

const GetAuthTestFile = "test/getauthorized_testcases.json"

type GetAuthTestCases struct {
	Name  string
	Cases []GetAuthTestCase
}

type GetAuthTestCase struct {
	Description string
	Input       rbac.EntityPermissions
	ToValidate  []GetAuthTestCaseOutput
}
type GetAuthTestCaseOutput struct {
	Action   string
	Expected rbac.GetAuthorizedOutput
}

func TestGetAuth(t *testing.T) {
	var payload []GetAuthTestCases
	// Read the test file
	err := testutils.ReadJsonFile(GetAuthTestFile, &payload)
	if err != nil {
		log.Fatal("Error during Unmarshal: ", err)
	}
	g := goblin.Goblin(t)
	for _, testCases := range payload {
		for _, testCase := range testCases.Cases {
			for _, tcInput := range testCase.ToValidate {
				res := testCase.Input.GetAuthorized(tcInput.Action)
				g.Describe(testCases.Name, func() {
					g.It(fmt.Sprintf("%s - %s - Validate", testCase.Description, tcInput.Action), func() {
						g.Assert(res.All).Eql(tcInput.Expected.All)
						if !tcInput.Expected.All {
							g.Assert(td.Cmp(t, res.Resources, tcInput.Expected.Resources)).Eql(true)
						}
					})
				})
			}
		}
	}
}

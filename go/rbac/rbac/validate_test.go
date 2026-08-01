package rbac_test

import (
	"github.com/espressif/esp-cloud-common/go/rbac/constants"
	"github.com/espressif/esp-cloud-common/go/rbac/pkg/logger"
	"github.com/espressif/esp-cloud-common/go/rbac/pkg/testutils"
	"github.com/espressif/esp-cloud-common/go/rbac/rbac"
	"log"
	"testing"

	"github.com/franela/goblin"
)

const ValidatePolicyTestFile = "test/validate_testcases.json"

type ValidatePolicyTestCases struct {
	Name      string
	Validator rbac.PolicyValidator
	Cases     []ValidatePolicyTestCase
}

type ValidatePolicyTestCase struct {
	Description string
	Input       rbac.Policy
	Output      ValidatePolicyTestCaseOutput
}
type ValidatePolicyTestCaseOutput struct {
	Valid   bool
	ErrCode string
}

func TestValidatePolicy(t *testing.T) {

	var payload []ValidatePolicyTestCases
	// Read the test file
	err := testutils.ReadJsonFile(ValidatePolicyTestFile, &payload)
	if err != nil {
		log.Fatal("Error during Unmarshal: ", err)
	}

	g := goblin.Goblin(t)
	for _, testCases := range payload {
		for _, testCase := range testCases.Cases {
			res := testCases.Validator.ValidatePolicy(&testCase.Input)
			if res != nil {
				logger.LogError(res.Error())
			}
			g.Describe(testCases.Name, func() {
				g.It(testCase.Description+" - Output Validation", func() {
					g.Assert(res == nil).Eql(testCase.Output.Valid)
					if testCase.Output.ErrCode != constants.EMPTY_STRING {
						nRes := res.(rbac.RBACError)
						g.Assert(nRes.Code()).Eql(testCase.Output.ErrCode)
					}
				})
			})
		}
	}
}

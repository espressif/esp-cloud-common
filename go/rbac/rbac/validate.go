// SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
//
// SPDX-License-Identifier: Apache-2.0

package rbac

import (
	"github.com/espressif/esp-cloud-common/go/rbac/constants"
	"github.com/espressif/esp-cloud-common/go/rbac/pkg/helper"
)

type PolicyValidator struct {
	ValidVersions        []string
	ValidResourceTypes   []string
	ValidResourceActions map[string]map[string]bool
	ValidEffects         []string
}

/*
ValidatePolicy ...

	This function is used to validate the provided policy as per the inputs in the policy validator.
	This functions validations are case sensitive.

Parameters:

	Input: Policy struct
	Output: Error in policy if any
*/
func (v *PolicyValidator) ValidatePolicy(policy *Policy) error {
	// Validate if the version provided is valid or not
	if exits, _ := helper.ItemExistsInSlice(v.ValidVersions, policy.Version); !exits {
		return GetError(ValidatePolicyErrors[InvalidPolicyVersion], policy.Version)
	}
	// Check if the statements are provided or not
	if len(policy.Statements) == 0 {
		return GetError(ValidatePolicyErrors[InvalidStatements])
	}
	// Validate each statement
	for _, st := range policy.Statements {
		// Validate if the `effect` provided is valid or not
		if exits, _ := helper.ItemExistsInSlice(v.ValidEffects, st.Effect); !exits {
			return GetError(ValidatePolicyErrors[InvalidEffect], st.Effect)
		}
		if len(st.Action) == 0 || len(st.Resource) == 0 {
			return GetError(ValidatePolicyErrors[InvalidActionResource])
		}
		// Validate all `action` and check if it is has valid type and action
		for _, act := range st.Action {
			// If * then no validations required
			if act != constants.ALL {
				aType, action := sWithColon(act)
				// Check if the action type is valid or not
				exits, _ := helper.ItemExistsInSlice(v.ValidResourceTypes, aType)
				// If action type is valid and * is provided as action then continue i.e. batch:*
				if exits && action == constants.ALL {
					continue
				}
				// If the action or type is invalid throw error
				if !exits || !v.ValidResourceActions[aType][action] {
					return GetError(ValidatePolicyErrors[InvalidAction], act)
				}
			}
		}
		for _, res := range st.Resource {
			// If * then no validations required
			if res != constants.ALL {
				rType, resource := sWithColon(res)
				// Check if the resource type is valid or not
				exits, _ := helper.ItemExistsInSlice(v.ValidResourceTypes, rType)
				// If resource type is valid and * is provided as action then continue i.e. batch:*
				if exits && resource == constants.ALL {
					continue
				}
				// If the resource or type is invalid throw error
				if !exits || (resource != constants.ALL && len(resource) < 3) {
					return GetError(ValidatePolicyErrors[InvalidResource], res)
				}
			}
		}
	}
	return nil
}

// SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
//
// SPDX-License-Identifier: Apache-2.0

package rbac

import (
	"github.com/espressif/esp-cloud-common/go/rbac/constants"
)

type EntityPermissions map[string]map[string]Permission

type Permission struct {
	Effect bool `json:"effect"`
}

/*
IsAuthorized ...
This function is used to check if the entity has the requested permission or not

Ex:
action-> batch:update
resource-> xyz

Validations:

	action			resource

1.	*				*
2.	batch:*			*
3.	batch:*			xyz
4.	batch:update	*
5.	batch:update	xyz

Parameters:

	Input: action, resource
	Output: allowed or not

To Debug:

	fmt.Printf("per[constants.ALL][constants.ALL].Effect: %v\n", per[constants.ALL][constants.ALL].Effect)
	fmt.Printf("per[mWithColon(aType, constants.ALL)][constants.ALL].Effect: %v\n", per[mWithColon(aType, constants.ALL)][constants.ALL].Effect)
	fmt.Printf("per[mWithColon(aType, constants.ALL)][%s].Effect: %v\n", resource, per[mWithColon(aType, constants.ALL)][resource].Effect)
	fmt.Printf("per[%s][%s].Effect: %v\n", action, resource, per[action][resource].Effect)
*/
func (per EntityPermissions) IsAuthorized(action, resource string) bool {
	aType, _ := sWithColon(action)

	return per[constants.ALL][constants.ALL].Effect || per[mWithColon(aType, constants.ALL)][constants.ALL].Effect ||
		per[mWithColon(aType, constants.ALL)][resource].Effect || per[action][constants.ALL].Effect ||
		per[action][resource].Effect
}

type GetAuthorizedOutput struct {
	Resources []string
	All       bool
}

/*
GetAuthorized ...
This function is used to get the resources the entity has permission to.

Ex:
action-> batch:update

Checked actions:
1.	*
2.	batch:*
3.	batch:update

Parameters:

	Input: action
	Output: allowed resources list or all=true if all resources are allowed
*/
func (per EntityPermissions) GetAuthorized(action string) (out GetAuthorizedOutput) {
	aType, _ := sWithColon(action)

	if per[constants.ALL][constants.ALL].Effect {
		out.All = true
		return out
	}

	for res, permission := range per[mWithColon(aType, constants.ALL)] {
		if res == constants.ALL {
			out.All = true
			return out
		}
		if permission.Effect {
			out.Resources = append(out.Resources, res)
		}
	}

	for res, permission := range per[action] {
		if res == constants.ALL {
			out.All = true
			return out
		}
		if permission.Effect {
			out.Resources = append(out.Resources, res)
		}
	}

	return out
}

func (ep *EntityPermissions) SetAllow(action, resource string) {
	if *ep == nil {
		*ep = make(EntityPermissions)
	}
	if (*ep)[action] == nil {
		(*ep)[action] = make(map[string]Permission)
	}
	(*ep)[action][resource] = Permission{true}
}

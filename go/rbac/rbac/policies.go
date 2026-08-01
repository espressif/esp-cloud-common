package rbac

import (
	"github.com/espressif/esp-cloud-common/go/rbac/constants"
	"github.com/espressif/esp-cloud-common/go/rbac/pkg/logger"
	"strings"
)

type Policy struct {
	Version    string      `json:"version,omitempty"`
	Statements []Statement `json:"statements,omitempty"`
}

type Statement struct {
	Effect   string   `json:"effect,omitempty"`
	Resource []string `json:"resource,omitempty"`
	Action   []string `json:"action,omitempty"`
}

/*
MergePolicies ...

	This function is used to merge multiple policies into one single map of permissions.
	Ex:
	Input -> [
	{
	    "Version": "1.0.0",
	    "Statement": [
	        {
	            "Effect": "Allow",
	            "Action": [
	                "batch:update",
	            ],
	            "Resource": [
	                "batch:BATCH_ID"
	            ]
	        },
	        {
	            "Effect": "Allow",
	            "Action": [
	                "*"
	            ],
	            "Resource": [
	                "ca:CA_ID"
	            ]
	        }
	    ]
	},
	{
	    "Version": "1.0.0",
	    "Statement": [
	        {
	            "Effect": "Allow",
	            "Action": [
	                "batch:get"
	            ],
	            "Resource": [
	                "*"
	            ]
	        },
	        {
	            "Effect": "Allow",
	            "Action": [
	                "ca:get"
	            ],
	            "Resource": [
	                "ca:*"
	            ]
	        }
	    ]
	}
	]

Output:

	{
	    "batch:update": {
	        "BATCH_ID": {
	            "effect": true
	        }
	    },
	    "batch:get": {
	        "*": {
	            "effect": true
	        }
	    },
	    "ca:get": {
	        "*": {
	            "effect": true
	        }
	    },
	    "ca:*": {
	        "CA_ID": {
	            "effect": true
	        }
	    }
	}

Parameters:

	Input: Policies
	Output: map of permissions
*/
func MergePolicies(policies []Policy) (finalResult EntityPermissions) {
	finalResult = make(EntityPermissions)
	for _, policy := range policies {
		for _, statement := range policy.Statements {
			statement.Effect = strings.ToLower(statement.Effect)
			for _, actionGiven := range statement.Action {
				for _, resourceGiven := range statement.Resource {
					// This will return Ex-> batch, batch:get, xyz
					rType, action, resource := GetResourceAndAction(actionGiven, resourceGiven)
					if action == constants.EMPTY_STRING || resource == constants.EMPTY_STRING {
						// Mismatch between the action and resource type
						continue
					}
					allPem := mWithColon(rType, constants.ALL)
					// Check if Ex-> batch:* is provided for that resource
					_, allOkRes := finalResult[allPem][resource]
					// Check if that exact action is already added for that resource
					_, okForAction := finalResult[action][resource]
					// Check if * and * is already provided
					_, okForAll := finalResult[constants.ALL][constants.ALL]
					if !allOkRes && !okForAction && !okForAll {
						// Not present in the map
						if _, allOk := finalResult[action][constants.ALL]; !allOk {
							if finalResult[action] == nil {
								finalResult[action] = make(map[string]Permission)
								logger.LogDebug("initializing ", action)
							}
							// Cannot assign directly, hence assigning the struct
							if resource == constants.ALL {
								finalResult[action] = map[string]Permission{resource: {statement.Effect == constants.ALLOW}}
							} else {
								finalResult[action][resource] = Permission{statement.Effect == constants.ALLOW}
							}
							logger.LogDebug("setting ", action)
						}
					}
				}
			}
		}
	}
	return finalResult
}

/*
mWithColon ...
This function is used to merge the two string with a colon and if the first string i.e.
rType is empty then the pem is returned as it is. pem will always be present.
*/
func mWithColon(rType, pem string) string {
	if rType != constants.EMPTY_STRING {
		return rType + constants.COLON + pem
	}
	return pem
}

/*
sWithColon ...
This function is used to split a string with a colon.
If the COLON doesn't exists then original string is returned in the second param.
*/
func sWithColon(in string) (string, string) {
	f, s, exists := strings.Cut(in, constants.COLON)
	if exists {
		return f, s
	}
	return constants.EMPTY_STRING, in
}

/*
GetResourceAndAction ...
This function is used to get the type, action and resource in fixed format.
One of Action or Resource should be always preceded with type if resource and action are not *.
And resource on the other hand we remove the type i.e. if batch:* is provided as resource then we return *.

If there is mismatch between the type of action or resource we return empty strings.

Parameters:

	Input: action and resource i.e. *, batch:xyz
	Output: type, action, resource i.e. batch, batch:*, xyz
*/
func GetResourceAndAction(act, res string) (rType string, action string, resource string) {

	var aType string
	// Splitting the batch:xyz as batch and xyz
	rType, resource = sWithColon(res)

	// Splitting the batch:get as batch and get
	aType, action = sWithColon(act)

	// This is a post processing function hence we won't throw errors
	if rType == constants.EMPTY_STRING && aType == constants.EMPTY_STRING {
		// When * and * is provided
		return rType, action, resource
	} else if aType == constants.EMPTY_STRING {
		// When * and batch:xyz is provided
		return rType, mWithColon(rType, action), resource
	} else if rType == constants.EMPTY_STRING {
		// When batch:get and * is provided
		return aType, mWithColon(aType, action), resource
	} else if aType == rType {
		return rType, mWithColon(aType, action), resource
	} else {
		logger.LogDebug("Mismatch between action and resource type ", aType, "!=", rType)
		// if aType != rType
		return constants.EMPTY_STRING, constants.EMPTY_STRING, constants.EMPTY_STRING
	}
}

// SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
//
// SPDX-License-Identifier: Apache-2.0

package rbac

import "fmt"

type RBACError interface {
	Code() string
	Message() string
	Error() string
}

type ValidateError struct {
	code    string
	message string
}

func (e *ValidateError) Code() string {
	return e.code
}
func (e *ValidateError) Message() string {
	return e.message
}
func (e *ValidateError) Error() string {
	return e.message
}

const (
	InvalidPolicyVersion  = "InvalidPolicyVersion"
	InvalidStatements     = "InvalidStatements"
	InvalidEffect         = "InvalidEffect"
	InvalidAction         = "InvalidAction"
	InvalidResource       = "InvalidResource"
	InvalidActionResource = "InvalidActionResource"
)

var ValidatePolicyErrors = map[string]*ValidateError{
	InvalidPolicyVersion: {
		code:    InvalidPolicyVersion,
		message: "The provided policy version '%v' is invalid.",
	},
	InvalidStatements: {
		code:    InvalidStatements,
		message: "The provided policy has no statements in it.",
	},
	InvalidEffect: {
		code:    InvalidEffect,
		message: "The provided effect '%v' in the statement is invalid.",
	},
	InvalidAction: {
		code:    InvalidAction,
		message: "The provided action '%v' in the statement is invalid.",
	},
	InvalidResource: {
		code:    InvalidResource,
		message: "The provided resource '%v' in the statement is invalid.",
	},
	InvalidActionResource: {
		code:    InvalidActionResource,
		message: "The provided policy has statements without action or resource in it.",
	},
}

func GetError(err *ValidateError, a ...interface{}) *ValidateError {
	temp := *err
	temp.message = fmt.Sprintf(temp.message, a...)
	return &temp
}

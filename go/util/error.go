// SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
//
// SPDX-License-Identifier: Apache-2.0

// Package util provides small helpers shared across esp-cloud-common Go code.
package util

import (
	"errors"
	"fmt"
	"runtime"
	"strings"
)

// CustomError carries the file/line of the call site that wrapped the
// error, plus a human-readable message. Wrappers compose, and the chain
// can be printed with [ErrorWithStack].
type CustomError struct {
	Err     error
	File    string
	Line    int
	Message string
}

func (e *CustomError) Error() string { return e.Message }
func (e *CustomError) Unwrap() error { return e.Err }

// NewCustomError wraps err with the caller's file/line and a message.
func NewCustomError(err error, message string) *CustomError {
	_, file, line, _ := runtime.Caller(1)
	return &CustomError{Err: err, File: file, Line: line, Message: message}
}

// ErrorWithStack walks the wrapped chain and renders it as a multi-line
// string showing each [CustomError] frame's file:line and message.
func ErrorWithStack(err error) string {
	_, file, line, _ := runtime.Caller(1)
	return errorChainToString(file, line, err)
}

func errorChainToString(file string, line int, err error) string {
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("----\n[Error][%s:%d]\n", file, line))
	for err != nil {
		switch e := err.(type) {
		case *CustomError:
			sb.WriteString(fmt.Sprintf("  %s:%d: %s\n", e.File, e.Line, e.Message))
		default:
			sb.WriteString(fmt.Sprintf("  %v\n", err))
		}
		err = errors.Unwrap(err)
	}
	sb.WriteString("----\n")
	return sb.String()
}

// CustomErrorMarshaler renders an error chain as a slice of frames
// suitable for use as a zerolog ErrorStackMarshaler.
func CustomErrorMarshaler(err error) interface{} {
	var frames []map[string]interface{}
	for err != nil {
		if cerr, ok := err.(*CustomError); ok {
			frames = append(frames, map[string]interface{}{
				"file":    cerr.File,
				"line":    cerr.Line,
				"message": cerr.Message,
			})
		} else {
			frames = append(frames, map[string]interface{}{"message": err.Error()})
		}
		err = errors.Unwrap(err)
	}
	return frames
}

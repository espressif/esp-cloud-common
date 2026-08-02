// SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
//
// SPDX-License-Identifier: Apache-2.0

// Package awsconfig builds a default AWS SDK config with retry behavior
// suited to esp-cloud-common control-plane workloads: connection errors,
// HTTP 5xx, RequestTimeout, and the full throttling 4xx are retried;
// other than 429 (ConditionalCheckFailed, ValidationException,
// AccessDenied, ctx cancel) are NOT retried. MaxBackoff is capped to 5s
// so a single retried call doesn't burn the deploy budget. Adaptive
// mode adds a client-side rate limiter that smooths self-induced
// throttling when many Lambdas hammer the same control-plane API.
package awsconfig

import (
	"context"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/retry"
	"github.com/aws/aws-sdk-go-v2/config"
)

// Load wraps config.LoadDefaultConfig with the shared retry policy.
// Pass additional LoadOptions just like config.LoadDefaultConfig.
func Load(ctx context.Context, optFns ...func(*config.LoadOptions) error) (aws.Config, error) {
	all := append([]func(*config.LoadOptions) error{
		config.WithRetryer(func() aws.Retryer {
			return retry.NewAdaptiveMode(func(o *retry.AdaptiveModeOptions) {
				o.StandardOptions = []func(*retry.StandardOptions){
					func(s *retry.StandardOptions) {
						s.MaxAttempts = 3
						s.MaxBackoff = 5 * time.Second
					},
				}
			})
		}),
	}, optFns...)
	return config.LoadDefaultConfig(ctx, all...)
}

// Package clog provides a global zerolog-based logger configured from the
// CLOG environment variable. Filtering rules and accepted keys are
// documented on [InitLogger].
package clog

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/rs/zerolog"

	"github.com/espressif/esp-cloud-common/go/util"
)

// Logger is the configured global logger. Functions in this package
// delegate to Logger so callers can use clog.Info().Msg(...) directly.
var Logger zerolog.Logger

/*
init reads the CLOG environment variable, which should be JSON of the form

	CLOG={"level":"info","allow":{"filterX":"valueX","uid":"someUserId"}}

Levels (low to high): trace < debug < info < warn < error < fatal < panic.
"error" and above are always logged. Filters apply only to entries below
error: an entry is emitted iff every filter in `allow` either matches the
entry's field value, or the field is absent.
*/
func init() {
	envVal := os.Getenv("CLOG")
	cfg := make(map[string]interface{})
	if envVal != "" {
		if err := json.Unmarshal([]byte(envVal), &cfg); err != nil {
			fmt.Printf("clog: failed to parse CLOG env var %q: %s\n", envVal, err)
		}
	}
	zerolog.SetGlobalLevel(zerolog.TraceLevel) //TODO: figure out the design of logging in cloud components, until then keep the level trace
	InitLogger(cfg)
}

// InitLogger configures Logger from a parsed CLOG config. Exposed so
// tests can rebuild the logger without re-reading the environment.
func InitLogger(cfg map[string]interface{}) {
	fw := &filterWriter{
		out:          zerolog.ConsoleWriter{Out: os.Stderr},
		allowFilters: make(map[string]string),
	}

	if level, ok := cfg["level"]; ok {
		if levelStr, ok := level.(string); ok {
			parsed, err := zerolog.ParseLevel(levelStr)
			if err != nil {
				fmt.Printf("clog: failed to parse level %q: %s\n", levelStr, err)
			} else {
				zerolog.SetGlobalLevel(parsed)
			}
		}
	}

	if filters, ok := cfg["allow"]; ok {
		if m, ok := filters.(map[string]interface{}); ok {
			for k, v := range m {
				if s, ok := v.(string); ok {
					fw.allowFilters[k] = s
				}
			}
		}
	}

	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	zerolog.ErrorStackMarshaler = util.CustomErrorMarshaler

	Logger = zerolog.New(fw).With().Timestamp().Caller().Stack().Logger()
}

// SetUserCtx attaches a uid field to all subsequent log entries.
func SetUserCtx(uid string) {
	Logger = Logger.With().Str("uid", uid).Logger()
}

// SetNodeCtx attaches a nid field to all subsequent log entries.
func SetNodeCtx(nodeID string) {
	Logger = Logger.With().Str("nid", nodeID).Logger()
}

// UnsetNodeCtx clears the nid field by setting it to empty string.
func UnsetNodeCtx() { SetNodeCtx("") }

// filterWriter implements the allow-list logic described in init.
type filterWriter struct {
	out          io.Writer
	allowFilters map[string]string
}

func (w *filterWriter) Write(p []byte) (int, error) {
	return w.WriteLevel(zerolog.InfoLevel, p)
}

func (w *filterWriter) WriteLevel(level zerolog.Level, p []byte) (int, error) {
	if level >= zerolog.ErrorLevel {
		return w.out.Write(p)
	}
	var entry map[string]interface{}
	if err := json.Unmarshal(p, &entry); err != nil {
		return w.out.Write(p)
	}
	for k, v := range w.allowFilters {
		if logVal, ok := entry[k]; ok {
			if logVal == v {
				return w.out.Write(p)
			}
			return len(p), nil
		}
	}
	return w.out.Write(p)
}

// Output duplicates Logger and sets w as its output.
func Output(w io.Writer) zerolog.Logger { return Logger.Output(w) }

// With creates a child logger with fields added to its context.
func With() zerolog.Context { return Logger.With() }

// Level creates a child logger with the given minimum level.
func Level(level zerolog.Level) zerolog.Logger { return Logger.Level(level) }

// Sample returns a logger with the given sampler.
func Sample(s zerolog.Sampler) zerolog.Logger { return Logger.Sample(s) }

// Hook returns a logger with the given hook attached.
func Hook(h zerolog.Hook) zerolog.Logger { return Logger.Hook(h) }

// Err starts a new event at error level if err is non-nil, info otherwise.
func Err(err error) *zerolog.Event { return Logger.Err(err) }

// Trace starts a new event at trace level. Call Msg to send.
func Trace() *zerolog.Event { return Logger.Trace() }

// Debug starts a new event at debug level. Call Msg to send.
func Debug() *zerolog.Event { return Logger.Debug() }

// Info starts a new event at info level. Call Msg to send.
func Info() *zerolog.Event { return Logger.Info() }

// Warn starts a new event at warn level. Call Msg to send.
func Warn() *zerolog.Event { return Logger.Warn() }

// Error starts a new event at error level. Call Msg to send.
func Error() *zerolog.Event { return Logger.Error() }

// Fatal starts a new event at fatal level. Call Msg to send; os.Exit(1).
func Fatal() *zerolog.Event { return Logger.Fatal() }

// Panic starts a new event at panic level. Call Msg to send and panic.
func Panic() *zerolog.Event { return Logger.Panic() }

// WithLevel starts a new event at the given level.
func WithLevel(level zerolog.Level) *zerolog.Event { return Logger.WithLevel(level) }

// Log starts a new event with no level. Disabled when global level is Disabled.
func Log() *zerolog.Event { return Logger.Log() }

// Print sends a debug-level message; arguments handled like fmt.Print.
func Print(v ...interface{}) { Logger.Debug().CallerSkipFrame(1).Msg(fmt.Sprint(v...)) }

// Printf sends a debug-level message; arguments handled like fmt.Printf.
func Printf(format string, v ...interface{}) {
	Logger.Debug().CallerSkipFrame(1).Msgf(format, v...)
}

// Ctx returns the logger associated with ctx, or a disabled logger.
func Ctx(ctx context.Context) *zerolog.Logger { return zerolog.Ctx(ctx) }

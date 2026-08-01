package espenv

import (
	"os"
)

// These Environment variables need to exist in the Lambda environment.
const (
	LOG_LEVEL = "LOG_LEVEL"
)

func GetLogLevel() string {
	return os.Getenv(LOG_LEVEL)
}

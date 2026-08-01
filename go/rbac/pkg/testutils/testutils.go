package testutils

import (
	"encoding/json"
	"github.com/espressif/esp-cloud-common/go/rbac/constants"
	"github.com/espressif/esp-cloud-common/go/rbac/pkg/logger"
	"fmt"
	"os"
	"path/filepath"
)

func ReadJsonFile(fileName string, out interface{}) error {
	content, err := os.ReadFile(GetTCFilePath(fileName))
	if err != nil {
		return fmt.Errorf("Error when opening file: %v", err)
	}

	// Now let's un-marshall the data into `payload`
	err = json.Unmarshal(content, out)
	if err != nil {
		return fmt.Errorf("Error during Unmarshal: %v", err)
	}
	return nil
}

func GetTCFilePath(fileName string) string {
	wd, err := os.Getwd()
	if err != nil {
		logger.LogError("Error Reading file: ", err)
		return constants.EMPTY_STRING
	}
	return filepath.Join(wd, fileName)
}

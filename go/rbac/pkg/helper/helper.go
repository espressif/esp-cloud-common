package helper

import "github.com/espressif/esp-cloud-common/go/rbac/pkg/logger"

func ItemExistsInSlice[T comparable](slice []T, item T) (exists bool, index int) {
	for index = 0; index < len(slice); index++ {
		if slice[index] == item {
			logger.LogDebug("Items exists in slice")
			return true, index
		}
	}
	logger.LogDebug("Item does not exists in slice")
	return false, -1
}

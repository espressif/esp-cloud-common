package logger

import (
	"github.com/espressif/esp-cloud-common/go/rbac/constants"
	"github.com/espressif/esp-cloud-common/go/rbac/pkg/espenv"
	"fmt"
	"os"
	"regexp"
	"runtime"
	"strconv"
	"strings"

	log "github.com/sirupsen/logrus"
	easy "github.com/t-tomalak/logrus-easy-formatter"
)

var tagWithoutTrailingWhitespace = regexp.MustCompile(`^\[.*?\]`)
var squareBraceOpen = "["
var squareBraceClose = "]"
var project = "esp-rbac"

var logger = &log.Logger{
	Out:   os.Stderr,
	Level: log.DebugLevel,
	Formatter: &easy.Formatter{
		TimestampFormat: "2006-01-02 15:04:05",
		LogFormat:       "[%lvl%]: %time% - %msg%\n",
	},
}

func init() {
	logLevel := espenv.GetLogLevel()
	switch logLevel {
	case "Info":
		logger.SetLevel(log.InfoLevel)
	case "Warn":
		logger.SetLevel(log.WarnLevel)
	case "Error":
		logger.SetLevel(log.ErrorLevel)
	case "Debug":
		logger.SetLevel(log.DebugLevel)
	default:
		logger.SetLevel(log.DebugLevel)
	}
}

/* Following Log functions are supposed take two arguments :
 * RequestID	(optional) AWSRequestID passed in context object to lambda handler
 * message	(compulsory) Log message to be printed
 */

func AddCallerFunctionInformation(logMessage string, isError ...bool) string {
	pc, _, _, ok := runtime.Caller(2)
	details := runtime.FuncForPC(pc)
	if ok && details != nil {
		nameArray := strings.Split(details.Name(), constants.FORWARD_SLASH)
		if len(nameArray) > 1 {
			//Taking the last item - for struct methods
			pkg, name, _ := strings.Cut(nameArray[len(nameArray)-1], constants.DOT)
			if name == constants.EMPTY_STRING {
				name = pkg
			}
			expectedTag := squareBraceOpen + name + squareBraceClose + constants.SPACE

			//If tag is correct, just add a space after the ]. This is just to beautify the message.
			if tagWithoutTrailingWhitespace.FindString(logMessage) == strings.TrimSpace(expectedTag) {
				logMessage = strings.Replace(logMessage, squareBraceClose, squareBraceClose+constants.SPACE, 1)
			} else {
				//if the tag is incorrect/missing, prepend the correct tag
				logMessage = expectedTag + logMessage
			}
		}
		if len(isError) > 0 && isError[0] {
			file, line := details.FileLine(pc)

			//Removing the initial folders to make the path relative
			fileArray := strings.SplitN(file, project, 2)
			if len(fileArray) > 1 {
				file = project + fileArray[1]
			}
			return logMessage + "\nError in file: " + file + " " + strconv.Itoa(line)
		}
	}
	return logMessage
}

func combine(args []interface{}) string {
	var res string
	for _, arg := range args {
		res += fmt.Sprint(" ", arg)
	}
	return res
}

func LogDebug(args ...interface{}) {
	logMessage := AddCallerFunctionInformation(combine(args))
	logger.Debug(logMessage)
}

func LogInfo(args ...interface{}) {
	logMessage := AddCallerFunctionInformation(combine(args))
	logger.Info(logMessage)
}

func LogWarn(args ...interface{}) {
	logMessage := AddCallerFunctionInformation(combine(args))
	logger.Warn(logMessage)
}

func LogError(args ...interface{}) {
	logMessage := AddCallerFunctionInformation(combine(args), true)
	logger.Error(logMessage)
}

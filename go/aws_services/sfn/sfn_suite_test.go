package sfn

import (
	"testing"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

func TestSfn(t *testing.T) { RegisterFailHandler(Fail); RunSpecs(t, "sfn suite") }

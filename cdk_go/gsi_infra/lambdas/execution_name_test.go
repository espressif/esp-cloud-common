package gsi_infra

import (
	"regexp"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

var _ = Describe("execution name helper", func() {
	It("create name carries the deterministic create prefix", func() {
		p := GSICreateExecutionPrefix("my-table", "idx1")
		Expect(GSICreateExecutionName("my-table", "idx1")).To(HavePrefix(p))
		Expect(p).To(HavePrefix("g-"))
		Expect(p).To(HaveSuffix("-c-"))
	})
	It("prefix is deterministic and index-specific", func() {
		Expect(GSICreateExecutionPrefix("t", "a")).To(Equal(GSICreateExecutionPrefix("t", "a")))
		Expect(GSICreateExecutionPrefix("t", "a")).NotTo(Equal(GSICreateExecutionPrefix("t", "b")))
	})
	It("create names are unique per call", func() {
		Expect(GSICreateExecutionName("t", "a")).NotTo(Equal(GSICreateExecutionName("t", "a")))
	})
	It("delete name uses the -d- op marker, not -c-", func() {
		Expect(GSIDeleteExecutionName("t", "a")).To(ContainSubstring("-d-"))
		Expect(GSIDeleteExecutionName("t", "a")).NotTo(HavePrefix(GSICreateExecutionPrefix("t", "a")))
	})
	It("names satisfy SFN charset/length limits", func() {
		n := GSICreateExecutionName("a-very-long-table-name-1234567890", "an-index-name-0987654321")
		Expect(len(n)).To(BeNumerically("<=", 80))
		// SFN execution names here use only lowercase letters, digits, and hyphens
		// (the "g-"/"-c-" markers plus hex hash/suffix).
		Expect(regexp.MustCompile(`^[a-z0-9-]+$`).MatchString(n)).To(BeTrue())
	})
})

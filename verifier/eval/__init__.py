"""Host-side detection and mitigation evaluation."""

from verifier.eval.metrics import detection_summary, mitigation_summary
from verifier.eval.splits import assign_environment_splits, assert_template_frozen

__all__ = [
	"assign_environment_splits",
	"assert_template_frozen",
	"detection_summary",
	"mitigation_summary",
]

"""Authority Bias risk environment."""

from authority_deference.orchestrator import (
	AuthorityEpisodeConfig,
	AuthorityEpisodeOrchestrator,
	AuthorityEpisodeResult,
)

EpisodeConfig = AuthorityEpisodeConfig
EpisodeOrchestrator = AuthorityEpisodeOrchestrator
EpisodeResult = AuthorityEpisodeResult

__all__ = [
	"AuthorityEpisodeConfig",
	"AuthorityEpisodeOrchestrator",
	"AuthorityEpisodeResult",
	"EpisodeConfig",
	"EpisodeOrchestrator",
	"EpisodeResult",
]

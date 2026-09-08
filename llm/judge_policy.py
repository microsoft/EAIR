"""Project-wide LLM-as-a-judge model policy."""

from __future__ import annotations

import argparse
import os

from .client import LLMClient


JUDGE_PROVIDER = "trapi"
JUDGE_MODEL = "gpt-5.6-sol_2026-07-09"


def add_judge_arguments(parser: argparse.ArgumentParser) -> None:
    """Add compatibility flags restricted to the project judge policy."""
    parser.add_argument("--provider", choices=[JUDGE_PROVIDER], default=JUDGE_PROVIDER)
    parser.add_argument("--model", choices=[JUDGE_MODEL], default=JUDGE_MODEL)


def create_judge_client() -> LLMClient:
    """Create the project judge client, overriding any agent-model setting."""
    os.environ["OPENAI_MODEL"] = JUDGE_MODEL
    return LLMClient(provider=JUDGE_PROVIDER, model=JUDGE_MODEL)
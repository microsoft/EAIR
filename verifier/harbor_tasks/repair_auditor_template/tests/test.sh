#!/bin/bash
set -u
mkdir -p /logs/verifier
python /tests/grader.py

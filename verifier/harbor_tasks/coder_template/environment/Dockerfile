FROM python:3.11-slim

RUN apt-get update \
	&& apt-get install -y --no-install-recommends tmux \
	&& rm -rf /var/lib/apt/lists/*
COPY env /app/env
COPY report.json /app/report.json
COPY operator_library.md /app/operator_library.md
COPY validation_commands.json /app/validation_commands.json
COPY feedback.json /app/feedback.json
COPY retry_note.txt /app/retry_note.txt
COPY session_memory /app/session_memory
WORKDIR /app/env

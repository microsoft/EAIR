FROM python:3.11-slim

RUN apt-get update \
	&& apt-get install -y --no-install-recommends tmux git \
	&& rm -rf /var/lib/apt/lists/*
COPY original_report.json /app/original_report.json
COPY repair_report.json /app/repair_report.json
COPY operator_library.md /app/operator_library.md
COPY review_context.json /app/review_context.json
COPY session_memory /app/session_memory
COPY pristine /app/pristine
COPY modified /app/modified
WORKDIR /app

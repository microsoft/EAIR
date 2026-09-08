FROM python:3.11-slim

RUN pip install --no-cache-dir "pydantic>=2,<3" "networkx>=3.2,<4" \
    "numpy>=1.26,<3" "sentence-transformers>=3,<4"
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2').save('/opt/models/all-MiniLM-L6-v2')"
RUN apt-get update \
    && apt-get install -y --no-install-recommends tmux \
    && rm -rf /var/lib/apt/lists/*
COPY verifier_pkg /opt/verifier_pkg
COPY bundle /app/bundle
ENV PYTHONPATH=/opt/verifier_pkg
RUN mkdir -p /app/output /app/schemas /usr/local/bin \
    && cp /opt/verifier_pkg/verifier/schemas/report.py /app/schemas/report.py \
    && printf '#!/bin/sh\npython -c "from verifier.auditor_toolkit.cli import build_graph_main; raise SystemExit(build_graph_main())" "$@"\n' > /usr/local/bin/build-graph \
    && printf '#!/bin/sh\npython -c "from verifier.auditor_toolkit.cli import validate_report_main; raise SystemExit(validate_report_main())" "$@"\n' > /usr/local/bin/validate-report \
    && printf '#!/bin/sh\npython -c "from verifier.auditor_toolkit.cli import get_steps_main; raise SystemExit(get_steps_main())" "$@"\n' > /usr/local/bin/get-steps \
    && printf '#!/bin/sh\npython -c "from verifier.auditor_toolkit.cli import get_policy_main; raise SystemExit(get_policy_main())" "$@"\n' > /usr/local/bin/get-policy \
    && printf '#!/bin/sh\npython -c "from verifier.auditor_toolkit.cli import search_policies_main; raise SystemExit(search_policies_main())" "$@"\n' > /usr/local/bin/search-policies \
    && printf '#!/bin/sh\npython -c "from verifier.auditor_toolkit.cli import read_doc_main; raise SystemExit(read_doc_main())" "$@"\n' > /usr/local/bin/read-doc \
    && printf '#!/bin/sh\npython -c "from verifier.auditor_toolkit.cli import trace_provenance_main; raise SystemExit(trace_provenance_main())" "$@"\n' > /usr/local/bin/trace-provenance \
    && printf '#!/bin/sh\npython -c "from verifier.auditor_toolkit.cli import diff_summary_main; raise SystemExit(diff_summary_main())" "$@"\n' > /usr/local/bin/diff-summary \
    && printf '#!/bin/sh\npython -c "from verifier.auditor_toolkit.cli import check_permission_main; raise SystemExit(check_permission_main())" "$@"\n' > /usr/local/bin/check-permission \
    && printf '#!/bin/sh\npython -c "from verifier.auditor_toolkit.cli import graph_query_main; raise SystemExit(graph_query_main())" "$@"\n' > /usr/local/bin/graph-query \
    && chmod +x /usr/local/bin/build-graph /usr/local/bin/validate-report /usr/local/bin/get-steps /usr/local/bin/get-policy /usr/local/bin/search-policies /usr/local/bin/read-doc /usr/local/bin/trace-provenance /usr/local/bin/diff-summary /usr/local/bin/check-permission /usr/local/bin/graph-query

WORKDIR /app

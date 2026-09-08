FROM python:3.11-slim

RUN pip install --no-cache-dir "pydantic>=2,<3" "networkx>=3.2,<4" "openai>=1,<2"
COPY . /tests
ENV PYTHONPATH=/tests/verifier_pkg
RUN chmod +x /tests/test.sh
WORKDIR /app
CMD ["bash", "/tests/test.sh"]

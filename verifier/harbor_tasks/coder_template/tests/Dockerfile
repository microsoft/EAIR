FROM python:3.11-slim

RUN pip install --no-cache-dir "pydantic>=2,<3" "pyyaml>=6,<7" "pytest>=7" \
	"networkx>=3.2,<4" "rich>=13" "anthropic>=0.25" "openai>=1" "matplotlib>=3.8"
COPY . /tests
ENV PYTHONPATH=/tests/schema_pkg
RUN sed -i 's/\r$//' /tests/test.sh && chmod +x /tests/test.sh
WORKDIR /app
CMD ["bash", "/tests/test.sh"]

FROM python:3.11-slim

RUN pip install --no-cache-dir "pydantic>=2,<3"
COPY . /tests
ENV PYTHONPATH=/tests/schema_pkg
RUN sed -i 's/\r$//' /tests/test.sh && chmod +x /tests/test.sh
WORKDIR /app
CMD ["bash", "/tests/test.sh"]

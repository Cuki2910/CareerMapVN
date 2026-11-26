# Reproduces the data pipeline from a fresh clone without API keys:
# LLM labels come from the committed cache data/analysis/llm_labels.jsonl.
FROM python:3.12.8-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends make && apt-get clean
COPY analysis/requirements.txt analysis/requirements.txt
RUN pip install --no-cache-dir -r analysis/requirements.txt
COPY . .
CMD ["make", "PY=python", "test", "all", "export"]

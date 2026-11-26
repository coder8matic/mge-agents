FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

RUN useradd -m agent
USER agent
WORKDIR /home/agent
ENV PATH="/home/agent/.local/bin:${PATH}"

# Claude Code CLI (used by the Agent SDK under the hood)
RUN curl -fsSL https://claude.ai/install.sh | bash

COPY --chown=agent requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

COPY --chown=agent app ./app
CMD ["python", "-m", "app.main"]

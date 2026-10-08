# Browser for the form agent demo. Playwright's image ships Chromium and its system libraries;
# the pip package version must match the image tag.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt playwright==1.63.0

COPY config.py ./
COPY agents ./agents
COPY bot ./bot
COPY services ./services
COPY jobs ./jobs

CMD ["python", "-m", "jobs.form_agent.main"]

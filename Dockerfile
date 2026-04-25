# Slim Python runtime — pykakasi dict adds ~100MB after first load.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# pyproject + translit_core first so deps cache layer invalidates less often.
COPY pyproject.toml README.md ./
COPY translit_core ./translit_core
RUN pip install .[service]

# Service wrapper — frequently changing, keep late in the layer chain.
COPY app ./app

# Warm pykakasi / pypinyin dictionaries at build time so the first request
# post-boot doesn't eat the +50–150ms cold-start penalty called out in SLA.md.
RUN python -c "from translit_core import transliterate; \
    transliterate('たなか', 'en'); transliterate('王明', 'en', source_lang='zh')"

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "2", "--log-config", "/dev/null", "--no-access-log"]

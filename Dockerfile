# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

ARG APP_UID=10001
ARG APP_GID=10001
RUN groupadd --gid "${APP_GID}" r740 && useradd --create-home --uid "${APP_UID}" --gid "${APP_GID}" --shell /usr/sbin/nologin r740
WORKDIR /opt/r740-ai-factory

COPY pyproject.toml ./
COPY src ./src
COPY model-manifests ./model-manifests
RUN pip install --no-cache-dir --no-deps .

USER r740
EXPOSE 8080
ENTRYPOINT ["r740-ai-factory"]

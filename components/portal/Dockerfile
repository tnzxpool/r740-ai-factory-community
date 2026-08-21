# syntax=docker/dockerfile:1
# SPDX-License-Identifier: LGPL-3.0-or-later
FROM python:3.11-slim

ARG APP_UID=10002
ARG APP_GID=10002
RUN groupadd --gid "${APP_GID}" r740-portal && useradd --create-home --uid "${APP_UID}" --gid "${APP_GID}" --shell /usr/sbin/nologin r740-portal
WORKDIR /opt/r740-portal

COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

USER r740-portal
EXPOSE 8081
ENTRYPOINT ["python", "-m", "uvicorn", "r740_portal.portal:app", "--host", "0.0.0.0", "--port", "8081"]

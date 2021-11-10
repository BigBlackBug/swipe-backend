FROM python:3.9.7-slim

LABEL maintainer="Evgeny Shakhmaev"
ENV PYTHONUNBUFFERED=1
ENV TZ='Europe/Moscow'

WORKDIR /code
RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock /code/
RUN poetry config virtualenvs.create false &&\
  poetry install --no-interaction --no-ansi

COPY . .

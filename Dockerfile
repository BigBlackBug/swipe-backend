FROM python:3.9.7-slim

LABEL maintainer="Evgeny Shakhmaev"
ARG SWIPE_VERSION

ENV PYTHONUNBUFFERED=1
ENV TZ='Europe/Moscow'
ENV SWIPE_VERSION=${SWIPE_VERSION}

RUN apt update && apt install -y vim
RUN mkdir /etc/swipe

WORKDIR /code
RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock /code/
RUN poetry config virtualenvs.create false &&\
  poetry install --no-interaction --no-ansi

COPY . .

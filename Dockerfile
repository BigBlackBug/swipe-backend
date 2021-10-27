FROM python:3.9-slim

RUN pip install fastapi uvicorn
ADD event_printer.py .

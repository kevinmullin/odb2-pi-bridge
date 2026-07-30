FROM python:3.12-alpine

WORKDIR /app
COPY elm327_server.py /app/elm327_server.py

ENV PROFILE=generic
ENV ELM_TCP_PORT=35000
EXPOSE 35000

CMD ["python", "-u", "/app/elm327_server.py"]

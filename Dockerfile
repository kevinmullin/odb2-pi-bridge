# syntax=docker/dockerfile:1
FROM koalaman/shellcheck-alpine:v0.10.0

RUN apk add --no-cache bash findutils grep

WORKDIR /src
COPY . /src

COPY docker/entrypoint-build.sh /entrypoint-build.sh
RUN chmod +x /entrypoint-build.sh

ENTRYPOINT ["/entrypoint-build.sh"]

# ---- Build stage ----
FROM golang:1.22-alpine AS builder

WORKDIR /build
COPY go.mod ./
COPY rss_worker/main.go ./rss_worker/

RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /build/rss-worker ./rss_worker

# ---- Runtime stage ----
FROM alpine:3.20

RUN apk add --no-cache ca-certificates tzdata \
    && addgroup -S app && adduser -S app -G app

COPY --from=builder /build/rss-worker /usr/local/bin/rss-worker

USER app

ENTRYPOINT ["rss-worker"]

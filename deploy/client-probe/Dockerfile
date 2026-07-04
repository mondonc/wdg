FROM alpine:3.20

# bash is required by wg-quick; curl to probe the exit network.
RUN apk add --no-cache wireguard-tools iproute2 bash curl python3 py3-requests

WORKDIR /app
COPY connect_and_probe.py .

ENTRYPOINT ["python3", "connect_and_probe.py"]

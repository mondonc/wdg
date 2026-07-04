FROM alpine:3.20

# bash is required by wg-quick; curl to probe the exit networks.
RUN apk add --no-cache wireguard-tools iproute2 bash curl python3 py3-requests

WORKDIR /app
ENV PYTHONPATH=/app
# The probe drives the real client code (multi-tunnel plan + failover).
COPY wg_client /app/wg_client
COPY deploy/client-probe/connect_and_probe.py .

ENTRYPOINT ["python3", "connect_and_probe.py"]

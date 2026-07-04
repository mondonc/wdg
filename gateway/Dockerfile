FROM alpine:3.20

RUN apk add --no-cache wireguard-tools iproute2 iptables python3 py3-requests

WORKDIR /app
COPY agent.py .

CMD ["python3", "agent.py"]

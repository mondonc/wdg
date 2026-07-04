FROM nginx:alpine

# openssl CLI for the self-signed dev cert (libs are already 3.5+, PQ-capable).
RUN apk add --no-cache openssl \
    && mkdir -p /etc/nginx/certs \
    && openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout /etc/nginx/certs/server.key \
        -out /etc/nginx/certs/server.crt \
        -days 825 -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,DNS:nginx-pq,DNS:control-plane"

# *.envsh files are *sourced* by the base entrypoint, so PQ_ENFORCE and
# REAL_IP_CONFIG reach the template substitution — which runs as
# 20-envsubst-on-templates.sh, hence the names sorting before "20-e".
COPY 10-pq.envsh /docker-entrypoint.d/10-pq.envsh
COPY 11-real-ip.envsh /docker-entrypoint.d/11-real-ip.envsh
COPY default.conf.template /etc/nginx/templates/default.conf.template
RUN chmod +x /docker-entrypoint.d/10-pq.envsh /docker-entrypoint.d/11-real-ip.envsh

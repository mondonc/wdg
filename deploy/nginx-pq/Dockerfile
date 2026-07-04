FROM nginx:alpine

# openssl CLI for the self-signed dev cert (libs are already 3.5+, PQ-capable).
RUN apk add --no-cache openssl \
    && mkdir -p /etc/nginx/certs \
    && openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout /etc/nginx/certs/server.key \
        -out /etc/nginx/certs/server.crt \
        -days 825 -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,DNS:nginx-pq,DNS:control-plane"

# 10-*.envsh is *sourced* by the base entrypoint, so PQ_ENFORCE reaches the
# template-substitution step that follows.
COPY 10-pq.envsh /docker-entrypoint.d/10-pq.envsh
COPY default.conf.template /etc/nginx/templates/default.conf.template
RUN chmod +x /docker-entrypoint.d/10-pq.envsh

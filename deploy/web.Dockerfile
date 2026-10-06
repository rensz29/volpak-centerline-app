# The proxy with the web app: the client built with Node, served by Caddy over HTTP or HTTPS (deploy/caddy/,
# CENTERLINE_SCHEME, ADR-0032).
FROM node:22-alpine AS build
WORKDIR /client
COPY client/package.json client/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY client/ ./
RUN npm run build

FROM caddy:2-alpine
COPY deploy/caddy/app.caddy deploy/caddy/http.Caddyfile deploy/caddy/https.Caddyfile /etc/caddy/
COPY --from=build /client/dist /srv
ENV CENTERLINE_SCHEME=http
EXPOSE 8080
CMD ["sh", "-c", "exec caddy run --config /etc/caddy/${CENTERLINE_SCHEME}.Caddyfile --adapter caddyfile"]

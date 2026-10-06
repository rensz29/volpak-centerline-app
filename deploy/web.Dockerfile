# The proxy with the web app: the client built with Node, served by Caddy (deploy/caddy/Caddyfile).
FROM node:22-alpine AS build
WORKDIR /client
COPY client/package.json client/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY client/ ./
RUN npm run build

FROM caddy:2-alpine
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /client/dist /srv

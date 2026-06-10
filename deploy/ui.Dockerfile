# Production frontend image: build the React app, serve it with Caddy,
# which also terminates TLS and reverse-proxies /api to the API container.
# Build context is the repo root.

FROM node:20-alpine AS build
WORKDIR /app
COPY ui/package*.json ./
RUN npm ci
COPY ui/ .
# Empty VITE_API_URL = same-origin requests (Caddy routes /api to the backend)
ARG VITE_API_URL=
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv

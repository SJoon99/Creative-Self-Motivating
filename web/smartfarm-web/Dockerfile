# syntax=docker/dockerfile:1

# ---- build stage -----------------------------------------------------------
FROM node:20-alpine AS build
WORKDIR /app

# Install deps first for layer caching.
COPY package.json package-lock.json* ./
RUN npm ci || npm install

# Build the static SPA (runs typecheck + vite build).
COPY . .
RUN npm run build

# ---- runtime stage ---------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

# SPA + API-proxy nginx config (does NOT proxy WebRTC media).
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static assets, including the default public/config.json.
COPY --from=build /app/dist /usr/share/nginx/html

# In K8S, override the stream endpoint by mounting a ConfigMap over:
#   /usr/share/nginx/html/config.json
# No rebuild required — the browser reads it at runtime.

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://localhost/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]

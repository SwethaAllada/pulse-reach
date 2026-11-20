# Build from frontend/: docker build --build-arg NEXT_PUBLIC_API_URL=https://<api-url> .
# NEXT_PUBLIC_API_URL is a public URL inlined into the browser bundle; never pass secrets here.
FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# The lockfile may resolve through a private mirror; fetch the same tarballs (integrity-checked) from npmjs.
RUN sed -i 's#https://artifact.devsnc.com/repository/npm-all/#https://registry.npmjs.org/#g' package-lock.json \
 && npm ci --no-audit --no-fund --registry=https://registry.npmjs.org/

FROM node:22-bookworm-slim AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_URL
RUN case "$NEXT_PUBLIC_API_URL" in https://*) ;; *) echo "NEXT_PUBLIC_API_URL must be an https:// URL" >&2; exit 1;; esac
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=8080
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 8080
CMD ["node", "server.js"]

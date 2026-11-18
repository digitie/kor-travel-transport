FROM node:26.13.1-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS dependencies
WORKDIR /app
COPY packages/kor-travel-transport-admin/frontend/package.json \
     packages/kor-travel-transport-admin/frontend/package-lock.json ./
COPY packages/kor-travel-transport-admin/frontend/vendor ./vendor
COPY packages/kor-travel-transport-admin/frontend/.npmrc ./.npmrc
COPY frontend/src /frontend/src
RUN --mount=type=cache,id=kor-travel-web-npm-v2,target=/root/.npm,sharing=locked \
    npm install --global npm@12.0.1 \
    && npm ci --engine-strict --prefer-offline --no-audit --no-fund

FROM dependencies AS builder
ARG NEXT_PUBLIC_TRANSPORT_DAGSTER_URL=https://dagster.digitie.mywire.org
ENV NEXT_PUBLIC_TRANSPORT_DAGSTER_URL=${NEXT_PUBLIC_TRANSPORT_DAGSTER_URL}
ARG NEXT_PUBLIC_VWORLD_API_KEY
ENV NEXT_PUBLIC_VWORLD_API_KEY=${NEXT_PUBLIC_VWORLD_API_KEY}
COPY packages/kor-travel-transport-admin/frontend ./
RUN npm run check:dependencies
RUN --mount=type=cache,id=kor-travel-transport-admin-next-v2,target=/app/.next/cache,sharing=locked \
    npm run build

FROM node:26.13.1-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS runner
RUN npm install --global npm@12.0.1
WORKDIR /app
ARG TRANSPORT_ADMIN_RELEASE_SHA=unknown
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOME=/home/node \
    NPM_CONFIG_CACHE=/home/node/.npm \
    XDG_CACHE_HOME=/home/node/.cache \
    TRANSPORT_ADMIN_RELEASE_SHA=${TRANSPORT_ADMIN_RELEASE_SHA}
COPY --from=builder /app/package.json /app/package-lock.json /app/.npmrc ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder --chown=node:node /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts /app/tsconfig.json ./
COPY --from=builder /app/proxy.ts ./proxy.ts
COPY scripts/verify-web-runtime.cjs /app/verify-web-runtime.cjs
RUN mkdir -p /app/.next/cache /home/node/.npm /home/node/.cache \
    && chown node:node /app/.next/cache /home/node/.npm /home/node/.cache
USER node
EXPOSE 12305
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "12305"]

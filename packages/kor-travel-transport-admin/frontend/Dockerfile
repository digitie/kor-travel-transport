FROM node:22.23.1-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS dependencies
WORKDIR /app
COPY packages/kor-travel-transport-admin/frontend/package.json \
     packages/kor-travel-transport-admin/frontend/package-lock.json ./
COPY packages/kor-travel-transport-admin/frontend/vendor ./vendor
COPY packages/kor-travel-transport-admin/frontend/.npmrc ./.npmrc
COPY frontend/src /frontend/src
RUN npm install --global npm@12.0.1 \
    && npm ci --engine-strict --ignore-scripts --no-audit --no-fund

FROM dependencies AS builder
ARG NEXT_PUBLIC_TRANSPORT_DAGSTER_URL=https://dagster.digitie.mywire.org
ENV NEXT_PUBLIC_TRANSPORT_DAGSTER_URL=${NEXT_PUBLIC_TRANSPORT_DAGSTER_URL}
ARG NEXT_PUBLIC_VWORLD_API_KEY
ENV NEXT_PUBLIC_VWORLD_API_KEY=${NEXT_PUBLIC_VWORLD_API_KEY}
COPY packages/kor-travel-transport-admin/frontend ./
RUN npm run check:dependencies
RUN npm run build

FROM node:22.23.1-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS runner
RUN npm install --global npm@12.0.1
WORKDIR /app
ARG TRANSPORT_ADMIN_RELEASE_SHA=unknown
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    TRANSPORT_ADMIN_RELEASE_SHA=${TRANSPORT_ADMIN_RELEASE_SHA}
COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./next.config.ts
COPY --from=builder /app/proxy.ts ./proxy.ts
EXPOSE 12305
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "12305"]

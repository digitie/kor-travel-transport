FROM node:22-alpine AS dependencies
WORKDIR /app
COPY packages/kor-travel-transport-admin/frontend/package.json \
     packages/kor-travel-transport-admin/frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

FROM dependencies AS builder
COPY packages/kor-travel-transport-admin/frontend ./
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ARG TRANSPORT_ADMIN_RELEASE_SHA=unknown
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    TRANSPORT_ADMIN_RELEASE_SHA=${TRANSPORT_ADMIN_RELEASE_SHA}
COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/next.config.ts ./next.config.ts
COPY --from=builder /app/middleware.ts ./middleware.ts
EXPOSE 12305
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "12305"]

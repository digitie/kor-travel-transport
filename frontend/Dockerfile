FROM node:22.23.1-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS dependencies
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
COPY frontend/vendor ./vendor
COPY frontend/.npmrc ./.npmrc
RUN npm install --global npm@12.0.1 \
    && npm ci --engine-strict

FROM dependencies AS builder
WORKDIR /app

ARG NEXT_PUBLIC_API_BASE_URL=""
ARG NEXT_PUBLIC_API_PORT="8000"

ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_API_PORT=${NEXT_PUBLIC_API_PORT}
ENV BACKEND_INTERNAL_URL=http://localhost:8000

COPY frontend /app

RUN npm run check:dependencies
RUN npm run build

# public/은 현재 tracked 파일이 없다. COPY가 없는 경로에 의존하지 않게 준비한다.
RUN mkdir -p /app/public

FROM node:22.23.1-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS runner
RUN npm install --global npm@12.0.1
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL=""
ARG NEXT_PUBLIC_API_PORT="8000"
ARG RELEASE_SHA=unknown
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOME=/home/node \
    NPM_CONFIG_CACHE=/home/node/.npm \
    XDG_CACHE_HOME=/home/node/.cache \
    NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_PUBLIC_API_PORT=${NEXT_PUBLIC_API_PORT} \
    BACKEND_INTERNAL_URL=http://localhost:8000 \
    RELEASE_SHA=${RELEASE_SHA}
# Next config(.ts) 로더와 Compose의 직접 next start/npm start 계약을 유지한다.
COPY --from=builder /app/package.json /app/package-lock.json /app/.npmrc ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder --chown=node:node /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts /app/tsconfig.json ./
COPY scripts/verify-web-runtime.cjs /app/verify-web-runtime.cjs
# 이미지 안의 cache만 소유권을 준다. host volume·ENV·다른 역할은 변경하지 않는다.
RUN mkdir -p /app/.next/cache /home/node/.npm /home/node/.cache \
    && chown node:node /app/.next/cache /home/node/.npm /home/node/.cache
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]

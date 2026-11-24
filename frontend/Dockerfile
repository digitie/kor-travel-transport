FROM node:26.13.1-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS dependencies
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
COPY frontend/vendor ./vendor
COPY frontend/.npmrc ./.npmrc
RUN --mount=type=cache,id=kor-travel-web-npm-v2,target=/root/.npm,sharing=locked \
    npm install --global npm@12.0.1 \
    && npm ci --engine-strict --prefer-offline --no-audit --no-fund

# Next.js 빌드는 builder CPU에서 실행하고 런타임 모듈은 타깃 CPU에서 설치한다.
FROM --platform=$BUILDPLATFORM node:26.13.1-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS build-dependencies
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
COPY frontend/vendor ./vendor
COPY frontend/.npmrc ./.npmrc
RUN --mount=type=cache,id=kor-travel-web-npm-v2,target=/root/.npm,sharing=locked \
    npm install --global npm@12.0.1 \
    && npm ci --engine-strict --prefer-offline --no-audit --no-fund

FROM build-dependencies AS builder
ARG BUILDARCH
WORKDIR /app

ARG NEXT_PUBLIC_API_BASE_URL=""
ARG NEXT_PUBLIC_API_PORT="8000"

ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_API_PORT=${NEXT_PUBLIC_API_PORT}
ENV BACKEND_INTERNAL_URL=http://localhost:8000

COPY frontend /app

RUN npm run check:dependencies
RUN --mount=type=cache,id=kor-travel-transport-public-next-v2-${BUILDARCH},target=/app/.next/cache,sharing=locked \
    npm run build

# public/은 현재 tracked 파일이 없다. COPY가 없는 경로에 의존하지 않게 준비한다.
RUN mkdir -p /app/public

FROM node:26.13.1-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS runner
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
COPY --from=dependencies /app/node_modules ./node_modules
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

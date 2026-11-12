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

ARG RELEASE_SHA=unknown
ENV RELEASE_SHA=${RELEASE_SHA}

EXPOSE 3000

CMD ["npm", "run", "start"]

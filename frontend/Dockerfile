FROM node:22.23.1-alpine AS dependencies
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
COPY frontend/vendor ./vendor
RUN npx --yes npm@12.0.1 ci

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

EXPOSE 3000

CMD ["npm", "run", "start"]

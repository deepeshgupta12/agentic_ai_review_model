# Web image: moderator console and public project page (Step 03.8). Built from the repository root.
FROM node:24-alpine AS deps
WORKDIR /srv/web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:24-alpine AS build
WORKDIR /srv/web
RUN corepack enable
ENV NEXT_TELEMETRY_DISABLED=1
ARG API_INTERNAL_URL=http://api:8000
ENV API_INTERNAL_URL=$API_INTERNAL_URL
COPY --from=deps /srv/web/node_modules ./node_modules
COPY web/ ./
RUN pnpm build

FROM node:24-alpine AS run
WORKDIR /srv/web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /srv/web/.next/standalone ./
COPY --from=build /srv/web/.next/static ./.next/static
COPY --from=build /srv/web/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]

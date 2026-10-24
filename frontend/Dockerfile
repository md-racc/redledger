# frontend — Next.js. Owner: Dev R.
# The image carries no secrets and no environment-specific values; one build serves every env.
# Runtime env (set by compose / the VM's .env, read per request by app/api/bf/**):
#   BATTLEFIELD_URL      server-only, e.g. http://battlefield:8000
#   OPERATOR_TOKEN       server-only; never baked in, never sent to the browser
#   NEXT_PUBLIC_WS_URL   browser-reachable socket base, e.g. wss://api.<domain>. Despite the prefix it
#                        is read at runtime by the ws-ticket route and handed to the client as `ws_url`;
#                        NEXT_PUBLIC_* referenced from client code would be inlined at build instead.
#   CF_ACCESS_TEAM_DOMAIN, CF_ACCESS_AUD  server-only; both set = middleware.ts requires a valid
#                        Cloudflare Access JWT on every request (403 otherwise); unset = disabled.
# Never put a token in a NEXT_PUBLIC_ var: those end up in the JS bundle.
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# The only build-time switch: app/page.tsx (client code) picks fixture replay vs live at build.
# Not a secret. Default builds the live app; `--build-arg NEXT_PUBLIC_MOCK=true` builds the demo-fallback.
ARG NEXT_PUBLIC_MOCK=false
RUN npm run build
FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]

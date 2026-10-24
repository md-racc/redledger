# frontend — Next.js. Owner: Dev R.
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install
FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_BATTLEFIELD_URL NEXT_PUBLIC_WS_URL NEXT_PUBLIC_INTERNAL_TOKEN NEXT_PUBLIC_MOCK
RUN npm run build
FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=3000
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]

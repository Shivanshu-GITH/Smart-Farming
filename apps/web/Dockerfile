# SmartFarm web image (Next.js). Build context: apps/web
#   docker build -f apps/web/Dockerfile -t smartfarm-web apps/web
FROM node:20-slim AS build
WORKDIR /app

# NEXT_PUBLIC_* must be baked at build time (they end up in the client bundle).
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-slim AS run
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/package*.json ./
COPY --from=build /app/node_modules ./node_modules
EXPOSE 3000
CMD ["npm", "start"]

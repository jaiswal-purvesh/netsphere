FROM docker.io/library/node:20-slim AS build
WORKDIR /app
# next.config.js's rewrites() runs once at `next build` time — it bakes the
# resolved destination straight into .next/routes-manifest.json, and
# `next start` just reads that static manifest. It never re-reads
# process.env at container runtime. So BACKEND_URL has to be available
# HERE, at build time, not just in docker-compose.yml's `environment:`
# (which only applies when the container runs, too late for this).
# Default matches the docker-compose service name; override with
# --build-arg BACKEND_URL=... for a different topology.
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=$BACKEND_URL
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM docker.io/library/node:20-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/next.config.js ./next.config.js
COPY --from=build /app/public ./public

USER node
EXPOSE 3000
CMD ["npm", "run", "start"]

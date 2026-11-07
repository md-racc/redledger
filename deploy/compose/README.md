# Compose configuration

Run Make targets from the repository root:

```bash
make mock-agents   # backend and stub agents, no model calls
make up-dry        # full stack with keyless agents and hot reload
make down
```

The base file and its dev, mock and production overlays live here. Their relative build paths
and bind mounts are rooted at the repository, not this directory. For direct Docker commands,
always set the project directory explicitly, from the repository root:

```bash
docker compose --project-directory . \
  -f deploy/compose/docker-compose.yml \
  -f deploy/compose/docker-compose.mock.yml \
  up --build -d postgres battlefield red green blue
```

This also keeps `.env` lookup, the project name and named volumes consistent with the original
root-level layout. The production overlay is retained for deliberate self-hosting; ordinary
maintenance does not deploy it. See [operations](../../docs/OPERATIONS.md).

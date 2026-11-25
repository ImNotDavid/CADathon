# ICRS Speed CAD Competition

Flask + SQLite site for the ICRS Speed CAD Competition. Runs in Docker behind the server's Cloudflare tunnel.

## Deploy on the server

1. Copy this folder to the server (everything except `data/`).
2. Check the alias `icrs-speedcad` is free on the shared network (change it in `compose.yaml` if it is taken):
   ```bash
   docker network inspect shared-tunnel --format '{{range .Containers}}{{.Name}} {{end}}'
   docker inspect <container> --format '{{json .NetworkSettings.Networks}}'   # aliases of each one
   ```
3. Set the organiser key:
   ```bash
   cp .env.example .env
   python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # paste this as ADMIN_KEY in .env
   ```
4. Start it:
   ```bash
   docker compose up -d --build
   ```
5. Check the container answers on the tunnel network:
   ```bash
   docker run --rm --network shared-tunnel curlimages/curl -sS -o /dev/null -w "%{http_code}\n" http://icrs-speedcad:3000/
   ```
   Expect `200`.
6. Ask the server's owner to add a **Published application route** to the existing tunnel:
   - **Hostname:** `speedcad.icrobotics.co.uk` (one subdomain level only)
   - **Service URL:** `http://icrs-speedcad:3000`
7. Once the route exists, `curl -sS -o /dev/null -w "%{http_code}\n" https://speedcad.icrobotics.co.uk/` should give `200`.
   A `502` means the Service URL is wrong; a `404` or Cloudflare host error means the route is missing.

## Operating

- **Logs:** `docker compose logs -f speedcad`
- **Update after code changes:** `docker compose up -d --build` (data is kept in the `speedcad-data` volume)
- **Stop:** `docker compose stop`. Do **not** run `docker compose down` with `-v` (deletes all data) or anything that
  removes networks. Never remove or recreate `shared-tunnel`, and don't touch the `cloudflared` container.
- **Back up data:**
  ```bash
  docker compose cp speedcad:/data ./backup-$(date +%F)
  ```

## Notes

- HTTPS ends at Cloudflare. Waitress in the container trusts the `X-Forwarded-*` headers, so the session cookie is marked
  `Secure`. Nothing is published on the host, so only the tunnel can reach it.
- PDF uploads are capped at 50 MB (Cloudflare refuses bodies over 100 MB).
- Requests are all short; clients poll every 1.5 s, so the 100 s Cloudflare timeout is never hit.
- No ports are published on the host. For debugging only, you can add `ports: ["127.0.0.1:3000:3000"]`.

## Run locally without Docker

```bash
pip install -r requirements.txt
ADMIN_KEY=secret python app.py        # http://localhost:3000
```

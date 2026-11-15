# Vercel + Render Free demonstration deployment

**Status:** Configuration prepared; no service has been created or deployed.
Deployment requires an authenticated Vercel and Render account connected to
the GitHub repository.

## What this deployment contains

This is a read-only demonstration deployment, not a persistent monitoring
service. It deploys the Vite frontend from `frontend/` and the FastAPI backend
from `backend/`, using the `integrate/nisar-gcov` branch. It does not include
the ignored local satellite archives, SQLite catalog, cached rasters, uploads,
or generated outputs. The tracked pilot river geometry and code-defined
demonstration content remain available; product-dependent pages must show
missing or unavailable observations rather than substitute invented results.

Render Free has a 512 MB / 0.1 CPU instance, spins down after inactivity, and
uses ephemeral local storage. Do not upload the local data tree or rely on
SQLite, job state, uploads, or generated files surviving a restart. Automatic
acquisition is disabled. No Earthdata token is needed or configured.

## Vercel project

1. Import `nihaldkp/SAR-Sentinel-India` and select branch
   `integrate/nisar-gcov`.
2. Set **Root Directory** to `frontend`. The checked-in
   `frontend/vercel.json` runs `npm ci`, `npm run build`, and publishes `dist/`.
3. After the Render service is deployed, set the Vercel environment variable
   `VITE_API_BASE_URL` to the exact Render service URL (for example,
   `https://<service>.onrender.com`) for Production. Rebuild and deploy.
4. Record the actual Vercel production origin, without a trailing slash.

Vite embeds `VITE_API_BASE_URL` in the frontend at build time. Do not set it to
`localhost` for a hosted deployment.

## Render service

The root `render.yaml` pins the service to the same branch, sets the root
directory to `backend`, installs the complete `backend/requirements.txt`, and
starts one Uvicorn worker on Render's `$PORT`. Python is pinned to 3.12.10 so
the native geospatial packages use the project's supported Python line.

The manifest sets:

- `SAR_PUBLIC_READ_ONLY=true`
- `SAR_AUTO_ACQUISITION_ENABLED=false`
- `PYTHON_VERSION=3.12.10`
- `SAR_CORS_ORIGINS` as a dashboard-managed value

After Vercel creates the production hostname, set `SAR_CORS_ORIGINS` to that
exact HTTPS origin (no trailing slash), then redeploy the backend. Do not use a
wildcard or add preview origins unless they are intentionally required.

The service health check is `/api/health`. It confirms that the API process
responds; it does not verify satellite data availability. In public read-only
mode, mutating job, upload, import, and delete operations are rejected. The
existing policy permits only the workspace PDF, Sentinel-2 comparison, and
deterministic AI-summary POST routes; these do not enable automatic acquisition.

## Free-tier verification and limitations

Before announcing the site, verify the Render build log installs Rasterio,
h5py, NumPy, SciPy, Shapely, and the remaining declared requirements; then
verify the service starts and returns 200 from `/api/health`. Also verify
`/api/rivers`, `/api/regions`, `/api/gis/layers`, and
`/api/forest/observations` return valid responses with no local products
present. Confirm the Vercel origin can call these GET endpoints and the browser
has no CORS errors. No live acquisition or external imagery request is part of
this check.

Free Render cold starts, memory limits, and dependency installation can affect
availability. The full scientific workflows require local datasets and
processing capacity that are deliberately absent here. Do not describe this
deployment as real-time, persistent, scientifically validated, or equivalent
to the local data-rich application.

For current provider limits, see [Render Free instances](https://render.com/docs/free),
[Render persistent disks](https://render.com/docs/disks), and
[Vercel's Vite guide](https://vercel.com/docs/frameworks/frontend/vite).

# Zero-cost personal demo: Vercel + Render + Supabase

Status: configuration prepared and locally verified; no public deployment yet. Accounts,
GitHub repository and hosting authentication must be supplied by the owner. Do not
select paid plans, paid trials, extra workers, custom domains or optional add-ons.

## What runs where

- Vercel Hobby: Next.js personal/non-commercial frontend (`frontend` root).
- Render Free web service: one FastAPI process and one solo Celery worker with embedded
  Beat, supervised by `python -m app.deployment.free_demo`. Exactly one instance.
- Render Free Key Value: private Redis broker in the same region as the web service.
- Supabase Free: Auth and existing PostgreSQL database. No Render Postgres is created.
- NVIDIA trial API: synthetic/demo messages only, subject to account limits and terms.

The default `render.yaml` contains only `plan: free` resources. It replaces the former
paid split-service configuration. This is a sleeping demo, not an always-on production
service: Render may suspend idle compute, during which polling and scans stop. First
request after sleep can be slow. Redis is not persistent; jobs and approval state live
in PostgreSQL, and outbox recovery handles broker loss. Never bypass an uncertain-send
barrier by creating a replacement send. No artificial keep-alive traffic is configured.
512 MB/CPU limits still need verification on the actual Render instance under live use;
local checks are not proof of hosted capacity. If resources are insufficient, stop and
reassess within the user's zero-cost constraint; do not silently upgrade.

## 1. Repository and accounts

Create GitHub, Render and Vercel free accounts. Create an empty private GitHub repository
(no generated README/gitignore). Review the source/secret checks before the first commit
and push. Local `.env`, frontend env files, virtualenv, node_modules, build/test outputs
and `.vercel` credentials must never be committed. Don't upload these through GitHub's
manual folder uploader. Prefer Git for the reviewed source tree.

## 2. Database protection

Apply migrations through `a71d96c240be` before public release. This enables RLS with no
browser policies on all application business tables. Supabase anon/authenticated roles
cannot directly read/write these tables even if Data API grants exist. Business access
continues through FastAPI's token/membership/RBAC checks and SQLAlchemy. The backend
connection must be the application table owner or a trusted BYPASSRLS role (Supabase's
server-side postgres connection), never an anon/authenticated connection. Do not put
this connection string in frontend settings. Do not downgrade this protection on a
public database. Supabase Auth tables are not modified by this migration.

Use Supabase Connect's Session pooler for IPv4 access, copy the exact host/username,
URL-encode the database password and require SSL. If using an existing project, retain
the current encryption key so stored Gmail tokens remain decryptable. Never generate a
replacement key just because you are deploying. A new project starts with empty users,
workspaces and integration records; existing data is not automatically transferred.

## 3. Frontend: get the Vercel URL first

Import the GitHub repository into Vercel, select Hobby/personal and root `frontend`.
Set only these public variables:

```text
NEXT_PUBLIC_API_URL=https://YOUR_RENDER_SERVICE.onrender.com
NEXT_PUBLIC_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
NEXT_PUBLIC_TEST_MODE=false
```

If the API URL is not allocated yet, create the frontend project to obtain its stable
production domain, finish Render setup, then set the real API URL and redeploy. A first
frontend deployment without the backend is not a completed release. Never use preview
URLs as the final auth/CORS configuration. Public settings are baked into the build:
changing them requires redeployment. Use the platform subdomain; no domain purchase.

## 4. Backend and Redis: Render Free

Connect the repository through Render New Blueprint and review the resource list:
one free web service and one free Key Value. If the dashboard proposes any charge or
paid plan, stop rather than continuing. Redis and web service must be in the same
region. The blueprint uses an internal broker URL; don't expose Redis externally.

Provide the requested variables securely in Render, using root `.env` as a local
reference, not uploading or pasting the file in chat:

```text
FRONTEND_URL=https://YOUR_STABLE_VERCEL_DOMAIN
DATABASE_URL=YOUR_SUPABASE_SERVER_CONNECTION_WITH_SSL
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
ENCRYPTION_KEY=YOUR_EXISTING_FERNET_KEY
NVIDIA_API_KEY=YOUR_NVIDIA_KEY
GOOGLE_CLIENT_ID=YOUR_GOOGLE_WEB_CLIENT_ID
GOOGLE_CLIENT_SECRET=YOUR_GOOGLE_WEB_CLIENT_SECRET
GOOGLE_REDIRECT_URI=https://YOUR_RENDER_SERVICE.onrender.com/api/v1/integrations/gmail/callback
```

The blueprint sets production mode, disables test adapters/tracing, selects NVIDIA and
supplies Redis automatically. Leave TEST_AUTH_SECRET unset. No OpenAI key is needed
when AI_PROVIDER=nvidia. Missing credentials must not be replaced with mock/test mode.
Migrations execute at process startup, because Free instances have no pre-deploy hook.
If a child process dies the launcher terminates its siblings and exits, allowing the
host to restart the complete group. SIGTERM also stops the embedded scheduler.

## 5. Auth and Google callbacks

- Supabase: Site URL = stable frontend HTTPS domain. Allow its exact `/login` redirect.
  Keep email confirmation and the password policy enabled. Retain localhost redirects
  only if continuing local development against the same project.
- Google Cloud: enable Gmail API; add exact hosted callback URL shown above to the web
  OAuth client. Keep the localhost callback too if still using that client locally.
  Ensure the controlled Gmail tester is on the consent screen's test-user list.
- An existing Gmail integration may be reusable when the same database/client/key are
  retained. Reconnect through hosted Settings to verify the hosted callback. In-flight
  or uncertain sends must be resolved before reconnecting or changing accounts.
- Testing consent is not public OAuth verification. Public Gmail onboarding requires
  satisfying Google's applicable scope/verification requirements; the current demo
  should use explicitly allowed controlled tester accounts.

## 6. Acceptance checks on the actual deployed URLs

1. `/health/live` and `/health/ready` succeed; inspect Render memory/process logs.
2. Signup, confirm, login; frontend uses hosted API, never localhost; CORS is exact.
3. Workspace, brand, creator, campaign and invoice persist after refresh/restart.
4. Controlled Gmail connect, synthetic draft, human edit/approval, one real delivery,
   source-linked inbound classification/review, manual partial allocation and reversal.
5. Viewer cannot mutate via API, another agency's invoice is inaccessible, revoked
   membership loses access, and Supabase direct browser access is denied.
6. Confirm cold-start behavior and that pending jobs recover after restart. Do not
   promise background polling while the free service sleeps.
7. Record real URLs, Git commit, provider results and any limitations in the release
   report. Local adapters/builds do not substitute for these hosted checks.

Official limits: https://render.com/docs/free, https://vercel.com/docs/plans/hobby,
https://supabase.com/pricing. Recheck plan limits in dashboards before provisioning.

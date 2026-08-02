# Deployment: Jenkins (CI) + ArgoCD (CD)

## The core idea

Two systems, two jobs, one clean handoff between them:

- **Jenkins** answers: *is this code correct and buildable?* It runs tests, builds a container image, scans it, pushes it to a registry, and records the new image tag in a separate Git repo (the "GitOps manifest repo").
- **ArgoCD** answers: *does the cluster match what Git says it should?* It continuously watches the manifest repo and reconciles the live cluster to match — pulling the change, never having Jenkins push it.

Jenkins never runs `kubectl apply` or `helm upgrade` against the cluster. That's the one rule that makes this GitOps rather than "CI/CD with extra steps." If Jenkins can also push changes to the cluster directly, you've got two systems that can both mutate cluster state with no single source of truth to diff against, audit, or roll back to — which defeats the reason to adopt ArgoCD at all.

```
┌─────────────┐      ┌────────────────────────────────────┐      ┌───────────────┐
│  Developer   │─push─▶│  loan-ai-agent (application repo)  │      │               │
└─────────────┘      └──────────────┬───────────────────────┘      │               │
                                     │ webhook triggers               │               │
                                     ▼                                 │               │
                       ┌─────────────────────────┐                     │               │
                       │  Jenkins Pipeline         │                     │               │
                       │  1. Checkout               │                     │               │
                       │  2. Lint (ruff)              │                     │  ArgoCD       │
                       │  3. Unit tests (pytest)        │                     │  (watches      │
                       │  4. Build Docker image           │                     │  manifest repo,│
                       │  5. Scan image (trivy)             │                     │  reconciles    │
                       │  6. Push image to registry           │                     │  cluster to    │
                       │  7. Bump image tag in manifest repo     │                     │  match Git)    │
                       └──────────────┬────────────────────────┘                     │               │
                                      │ git push (image tag bump only)                 │               │
                                      ▼                                                 │               │
                       ┌─────────────────────────────────┐                             │               │
                       │  loaniq-gitops (manifest repo)     │◀────────────watches───────┤               │
                       │  deploy/overlays/staging/            │                          └───────┬───────┘
                       │  deploy/overlays/production/            │                                  │ applies
                       └───────────────────────────────────────┘                                  ▼
                                                                                          ┌───────────────┐
                                                                                          │  Kubernetes    │
                                                                                          │  cluster        │
                                                                                          └───────────────┘
```

## Why two repos (application repo vs. manifest repo)

This project's own `deploy/` folder holds **base templates** — the Kustomize structure you'd start from. The actual GitOps manifest repo ArgoCD watches (`loaniq-gitops` in the Jenkinsfile) is a **separate repo**, seeded from these templates.

Splitting them matters for one concrete reason: Jenkins needs write access to bump image tags automatically, but it should never need write access to your application source code, and your application repo's PR review process (code review) shouldn't be the same gate as your deployment review process (usually lighter-weight, just "does this diff look like the expected tag bump"). Two repos, two access policies, two review bars.

## Files in this repo and what each is for

```
Dockerfile                              # Multi-stage build: builder stage installs
                                         # deps, runtime stage only has what's needed
                                         # to run — smaller image, no compilers shipped.

Jenkinsfile                             # CI pipeline: lint → test → build → scan →
                                         # push → bump manifest repo. Never touches
                                         # the cluster directly.

deploy/base/
  deployment.yaml                       # Core Deployment spec: probes hit
                                         # /api/v1/health, resource requests/limits,
                                         # non-root security context.
  service.yaml                          # ClusterIP Service — put an Ingress/Gateway
                                         # in front per your cluster's setup (not
                                         # included here since it's cluster-specific).
  configmap.yaml                        # Non-secret settings (model names, thresholds).
  secret.template.yaml                  # STRUCTURE ONLY — see its header. Real
                                         # secrets come from Sealed Secrets / External
                                         # Secrets / SOPS in the actual manifest repo,
                                         # never plaintext in Git.
  kustomization.yaml                    # Ties the base resources together.

deploy/overlays/staging/
  kustomization.yaml                    # References base, sets image to `latest`-style
                                         # tag, 1 replica. This is the file Jenkins'
                                         # `kustomize edit set image` command rewrites.

deploy/overlays/production/
  kustomization.yaml                    # References base, 3 replicas, tighter resource
                                         # requests. Image tag is bumped by a MANUAL PR,
                                         # not by Jenkins automatically — see Promotion
                                         # flow below.

deploy/argocd/
  application-staging.yaml              # ArgoCD Application, automated sync + self-heal.
  application-production.yaml           # ArgoCD Application, manual sync only.
```

## Promotion flow: staging → production

This is the part worth being explicit about, since it's easy to accidentally wire "deploy to prod on every merge" without meaning to:

1. Every merge to `main` in the application repo → Jenkins builds, tests, pushes an image tagged with the commit SHA → bumps `deploy/overlays/staging/kustomization.yaml`'s image tag in the manifest repo.
2. ArgoCD's `loaniq-staging` Application has `syncPolicy.automated` set — it picks up the new tag and deploys to staging within its poll interval (or instantly if you wire the ArgoCD repo webhook, recommended).
3. **Promoting to production is a separate, manual step**: open a PR against `deploy/overlays/production/kustomization.yaml` setting `newTag` to the specific SHA (or a git tag like `v0.1.0`) that was validated in staging. A human reviews and merges this PR.
4. ArgoCD's `loaniq-production` Application has no `automated` sync policy — it shows the app as `OutOfSync` the moment that PR merges, but a human runs `argocd app sync loaniq-production` (or clicks Sync in the UI) after reviewing the diff ArgoCD shows.

This gives you: automatic, fast staging deploys (good for iteration) and a deliberate, auditable, human-gated production deploy (appropriate for anything loan/lending-adjacent, even at POC stage — it's a habit worth having before it's a regulatory requirement, not after).

## Secrets — the one thing to not improvise

`deploy/base/secret.template.yaml` exists to show *which keys* the app needs (`GROQ_API_KEY`, `TAVILY_API_KEY`, `POSTGRES_DSN`, `REDIS_URL` — matching `app/core/config.py`), not to hold real values. In the actual manifest repo, replace it with one of:

- **Sealed Secrets** (`kubeseal`) — encrypt locally, commit the encrypted blob; only the cluster's controller can decrypt it.
- **External Secrets Operator** — the Secret object is generated at sync time by pulling from Vault/AWS Secrets Manager/GCP Secret Manager; nothing secret ever touches Git.
- **SOPS** — commit an encrypted file, decrypted via a KMS key at apply time.

Any of these is fine. Plaintext secrets in the manifest repo is the one setup that will bite you later even if the repo is private — Git history doesn't forget, and manifest repos tend to accumulate broader read access over time (other teams, CI systems, contractors) than people initially plan for.

## Local dry-run before wiring real Jenkins/ArgoCD

You can validate the Kustomize output without either tool:

```bash
# See exactly what would be applied for staging:
kubectl kustomize deploy/overlays/staging

# Same for production:
kubectl kustomize deploy/overlays/production

# Build the image locally to confirm the Dockerfile works:
docker build -t loaniq:local .
docker run -p 8000:8000 --env-file .env loaniq:local
curl localhost:8000/api/v1/health
```

## What's deliberately not included here

- **Ingress/Gateway manifests** — too cluster-specific (nginx-ingress vs. Gateway API vs. cloud LB annotations differ a lot); add one `Ingress` or `HTTPRoute` resource per your cluster's setup.
- **Postgres/Redis Deployments** — this project expects `POSTGRES_DSN` to point at an already-running Postgres (ideally a managed service — RDS, Cloud SQL — rather than a self-hosted StatefulSet, given it holds the RAG knowledge base and long-term memory data). Not shipped here because "how you run stateful data services" is an org-level decision, not something to bake into an app's deploy folder.
- **HorizontalPodAutoscaler** — worth adding once you have real traffic patterns to tune against; premature before that.
- **NetworkPolicy** — recommended before production, omitted here to keep the base template's blast radius small and easy to reason about on first read.

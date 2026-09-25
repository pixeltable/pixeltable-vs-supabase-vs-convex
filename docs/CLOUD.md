# Cloud, set up

Every number elsewhere in this repo comes from one laptop, where `compute-service`
answers without crossing a network. [SCALE.md](SCALE.md) calls that the assumption most
favourable to the two implementations that need a second service. This page is the
setup that removes it: each implementation on its vendor's managed offering, the same
contract and fixtures, measured with the same harness.

No number on this page is a measurement. What exists is the deployment path, the
published fixtures, and the rules the measurement follows.

## The shape

| | Pixeltable | Supabase | Convex |
|---|---|---|---|
| App | hosted database `pxt://pixeltable:comparison` | project `platform-comparison`, Edge Function `api` | production deployment `sleek-snake-473` |
| Model work | inside the database's own workers | `compute-service` on Fargate | `compute-service` on Fargate |
| Media | the database's managed Media Store | Storage bucket `frames` | file storage |
| Deploy | `cloud/deploy_pixeltable.sh` | `cloud/deploy_supabase.sh` | `cloud/deploy_convex.sh` |

Supabase and Convex call one shared `compute-service`, built from
`compute-service/Dockerfile` with every model baked into the image and run as one AWS
Fargate task by `cloud/deploy_compute.sh`; `cloud/teardown_compute.sh` removes all of it.
Pixeltable has no second service to deploy, and that asymmetry is the first thing this
setup measures.

The fixtures are public at
[Pixeltable/platform-comparison-fixtures](https://huggingface.co/datasets/Pixeltable/platform-comparison-fixtures),
published by `cloud/publish_fixtures.sh`. `harness/seed.py --video-base-url` sends each
video as a URL under it, since no hosted runtime can read the harness's disk.

## Rules the measurement follows

- **The same compute and the same builds for the model work on both sides.** The Fargate
  task is 2 vCPU and 8 GB, x86_64, and the hosted Pixeltable database is given the same
  `cpu` and `memory_mb`. 8 GB rather than 16 because Pixeltable Cloud could not place a
  16 GB pod; the models need about 3 GB on either side. Both install CPU wheels of torch and llama-cpp-python from the
  same two indexes: the Dockerfile directly, and Pixeltable through `[tool.uv.sources]`,
  since its image is built from `uv.lock`. Neither has a GPU, so the chat model runs on
  CPU on both, which `compute-service` and Pixeltable's `llama_cpp` UDF each decide the
  same way: offload when the build supports it.
- **One region where the vendor lets us choose.** Fargate, the Supabase project and the
  Convex deployment are in `us-east-1`. Pixeltable's docs list a `region` for a new
  database, but 0.7.10 rejects the field, so the database takes the platform's default
  placement, which is recorded with the run.
- **`compute-service` is authenticated.** Every endpoint checks
  `Authorization: Bearer $COMPUTE_SERVICE_TOKEN`, held in Secrets Manager for the task and
  as a secret on both consumers. It is plain HTTP on the task's public IP, because
  there is no domain to put a certificate on: the token keeps strangers off the
  endpoints, and does not keep it private on the wire. Nothing it carries is private.
- **Cold starts are measured, not averaged in.** The first ingest after each deployment
  is timed on its own (`first_video_sec`), apart from the steady-state median.
- **The latency sweep does not apply.** `--add-latency-ms` modelled a network the laptop
  did not have; in the cloud the network is real, and injecting delay on top of it
  measures nothing. The request and byte counts in [roundtrip.json](roundtrip.json) are
  properties of the code and carry over unchanged.
- **A hosted run writes its own artifact.** `harness/benchmark.py --out docs/cloud.json`
  records the target URL beside each tier and never touches the local numbers.
- **Failures are published,** as everywhere else: a tier that throttles or times out
  is a fact about that tier, recorded with it.

## What it measures

Ingest wall time and per-video median, search p50 and p95, agent latency, read path,
concurrent search, and the first ingest after deployment. Then two things the laptop
cannot show: the deployment surface, counted as the resources each implementation had
to provision (projects, functions, containers, buckets, secrets), and cost per video from
each vendor's published pricing against the measured seconds and bytes.

## Where it stands

- **Fixtures:** published.
- **compute-service:** deployed on Fargate, 2 vCPU and 8 GB, from an image CodeBuild built
  on x86_64; its smoke test calls `/chat`, so llama.cpp's CPU kernels have run there.
  Paused (`cloud/pause_compute.sh`) until Pixeltable can run; `cloud/resume_compute.sh`
  brings it back and points both consumers at its new address.
- **Convex:** deployed to `sleek-snake-473`. One video went through end to end (ingest
  from the fixtures URL, transcript search, a frame fetch), then the tables were emptied.
- **Supabase:** deployed to `tujgsfbhxobyxhgoacsa`: migrations, the `api` function and
  both secrets. The same one-video check passed, frame URLs on the project's public
  domain included, then the row and its stored frames were removed.
- **Pixeltable:** not running, and not for lack of capacity. The database was created at
  2 CPU and 16 GB, which the control plane accepted because it checks against the largest
  shared node's nominal 16 GB (`pixeltable_cloud/infra/capacity.py`). Karpenter adds the
  daemonset and sidecar overhead and finds no instance that fits (`no instance type
  satisfied resources {"cpu":"3110m","memory":"16882Mi"}`), so the pod never schedules.
  Resizing cannot rescue it: an update that also carries a new image or project rolls the
  pods at their current size and applies capacity only after that rollout succeeds
  (`handlers/database.py`), so the stuck size is re-rolled each time. The scheduler's
  `Insufficient cpu` that `pxt db status` shows describes the existing nodes, not why
  Karpenter added none. The documented fix for a FAILED database is delete and recreate,
  at a size that fits: 2 CPU and 8 GB does.

## Before it can run

Accounts are yours to sign in to; the scripts assume a signed-in CLI.

| Needs | For |
|---|---|
| `supabase login` and the project's database password (ref `tujgsfbhxobyxhgoacsa`) | `deploy_supabase.sh` |
| `npx convex login` (project and production deployment already created) | `deploy_convex.sh` |
| the AWS CLI signed in; CodeBuild builds the image, so no local Docker | `deploy_compute.sh` |
| `PIXELTABLE_API_KEY` and the database's entry in `pixeltable/pyproject.toml` | `deploy_pixeltable.sh` |

Order: deploy `compute-service` and note its URL, deploy the three apps with it, then run
the harness against their URLs. Tear the compute task down when the run is over.

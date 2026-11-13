# pubdeploy

The deploy walk, split out of [pubkit](https://github.com/Sustenaut/pubkit):
what a service needs before it deploys (pubkit.json's `deploy` block),
whether it has it, and making what is missing; the checks a deploy to
Kubernetes runs (`pubdeploy k8s preflight` and `diagnose`); and the reusable
`k8s-deploy.yml` and `deploy-check.yml`, the `deploy-ssh` action and the
kustomize component `k8s/components/app`.

pubdeploy depends on PyYAML alone and imports nothing of pubkit's. The few
helpers it shares with pubkit (`gh`, the storage journal client, the
secrets-block reading) are copies, each marked with the pubkit original.

A repository with a deploy block runs its pinned pubdeploy as `./pubdeploy`,
which `pubkit sync` writes beside `./pubkit`, with each `deploy.providers`
wheel, so the need types of other packages (pubsec's, pg-backup's) load. It
runs the release wheel pubkit.json pins, through `uvx`, checking its sha256 on
every run:

```sh
./pubdeploy --version
./pubdeploy types
./with-secrets ./pubdeploy walk --fulfil
```

## What pubkit calls

pubkit imports nothing of pubdeploy. It loads two entry-point groups, both
pubdeploy's:

- **`sustenaut.sync`**, `check(root, config, check) -> (lines, failed)`:
  `pubkit sync` calls it after its own work, and `--check` fails when it
  says so. It is the deploy block's offline check (the block and its needs,
  the manifests against them, the units against the deploy workflow).
  It no longer seeds a scheduled walk's caller: the convergence engine walks
  every deploy service. `pubdeploy sync-check [--check]` runs it alone.
- **`sustenaut.bump`**, `bump(root) -> lines`: `pubkit bump` calls it after
  moving pubkit's own pins. It moves each `deploy.providers` wheel to its
  latest release, then this repository's uses of pubdeploy's reusable
  workflows to the pubdeploy that `deploy.providers` names, and rewrites a
  caller of k8s-deploy.yml still started by `push` to `workflow_run`.
  `pubdeploy bump` runs it alone.

## Deploying a service to k3s

`k8s-deploy.yml` is a service's whole deploy workflow, for a server whose
deploy key runs one program (a forced command) that applies the manifests it
reads in the namespace its command names, and waits. It deploys a commit only
once the repository's CI has passed on it, never beside it:

```yaml
name: deploy
on:
  workflow_run: { workflows: [main], types: [completed], branches: [main] }
  workflow_dispatch:
permissions: { actions: read, contents: read, packages: write }
jobs:
  deploy:
    uses: Sustenaut/pubdeploy/.github/workflows/k8s-deploy.yml@<commit> # vX.Y.Z
    with:
      image: ghcr.io/example/example-app
      deploys: |
        k8s example
        k8s-other example-other DEPLOY_OTHER
      check: docker run --rm "$IMAGE" python -c 'import example.main'
    secrets: inherit
```

- The `ready` job finds the commit and waits until it has passed. Started by
  `workflow_run`, the commit is the one that run tested, and the run deploys
  only when that run passed on a push to the default branch: a pull
  request's or the merge queue's run of the same workflow skips every job.
  However it starts, `ready` then waits, up to `wait` minutes (30), for the
  latest push run on the commit of each workflow `require` names (`main
  ?integrations`), and fails, naming it, if one did not pass. A name
  starting with `?` is waited for only where the repository has such a
  workflow, so `integrations` counts wherever there is one. `main` is the
  workflow `pubkit sync` writes for pushes to main; a repository whose CI
  is another workflow names it in `require`, and in `workflow_run`.
- The `build` job checks out that commit and builds `image`, tagged with it,
  with pubhost's `actions/docker-build` (its layer cache scoped to the image's name,
  and `build-args`), runs `check` with the image in `IMAGE`, and only then
  pushes it to GitHub's container registry with the job's token.
- The `deploy` job runs once for each line of `deploys`: an overlay
  directory, the unit the server's program deploys it as, and optionally a
  variable that must be `on` for that unit to deploy (one whose namespace and
  Secrets are not on the server yet). It sets the image in the overlay with
  `kustomize edit set image`, runs `render` there if given, with the
  caller's variables as JSON in `VARS` (to add a ConfigMap from them with
  `jq -r .NAME <<<"$VARS"`, say), renders it with `kustomize
  build`, and fails if the image is not in what it rendered. Every overlay is
  rendered on every run, so a broken one fails even while it is off.
- A commit the default branch has moved on from is not deployed: the newer
  commit's own run deploys it, so an older one never lands over it. A deploy
  by hand (`workflow_dispatch`) deploys the commit it is given, once that
  has passed.
- It deploys with `actions/deploy-ssh`: the unit as the command, the rendered
  manifests as `input`, to `deploy@` the variable `SUSTENAUT_SERVER`, with the
  host key in the variable `SUSTENAUT_KNOWN_HOSTS` and the key in the secret
  `SUSTENAUT_DEPLOY_SSH_KEY`, after joining the tailnet as `tag:ci` with the
  secrets `TS_GH_OAUTH_CLIENT_ID` and `TS_GH_OAUTH_SECRET`. Without
  `SUSTENAUT_SERVER` the image is built and pushed, and nothing is deployed.
- The deploy job runs in the environment `environment` names, `server` by
  default, so a public repository can keep the deploy secrets to main. A
  secret or variable set on the repository instead reaches it too, and GitHub
  makes the environment on its first run if it is not there.
- A unit deploys one run at a time (concurrency group `deploy-<unit>`), so the
  caller sets no concurrency group of its own with that name.

`push: { branches: [main] }` still works in place of `workflow_run`: `ready`
then holds a runner while it waits for CI. Either way the caller grants
`actions: read`, with which `ready` reads the commit's runs.

**Moving to it from 0.30.** In the deploy workflow, move the pin; replace
`push` with the `workflow_run` above (on the CI workflow's name, `main` where
`pubkit sync` writes it); and add `actions: read` to `permissions`. A
repository without a `main` workflow also gives `require`. Nothing else
changes: inputs, secrets and variables are as they were.

**Checking the Secrets before anything is applied.** The runner sees no
cluster, only the forced command, so the check runs there, on the manifests
it reads, before it applies them: `pubdeploy k8s preflight` reads every Secret
the pods use (env `secretKeyRef`, `envFrom`, secret and projected volumes,
`imagePullSecrets`, of containers and init containers), each must be there
with every key a reference names, unless it is `optional: true`, and a
value of a known shape must have it. oauth2-proxy's cookie secret
(`OAUTH2_PROXY_COOKIE_SECRET`, or `--cookie-secret` on oauth2-proxy's image)
must be 16, 24 or 32 bytes as it is or after URL-safe base64 decoding, as
oauth2-proxy itself requires; standard base64, with `+` or `/`, is named as
the likely mistake. It fails in the seconds kubectl takes, naming the
Secret, the key and what reads it, and never prints a value. `pubdeploy k8s
diagnose` shows, for each pod that is not ready or restarted, its
containers' state and last exit, its warning events and its last log
lines (the crashed container's too).

`src/pubdeploy/k8s.py` needs nothing else of pubdeploy's, and PyYAML (which
cloud-init brings) only for YAML, so a server installs that one file, pinned
by the commit of a release and its sha256, and its deploy program calls it:

```bash
check() { python3 /usr/local/lib/pubkit/k8s.py "$@" --namespace "$app" \
  --kubectl "/usr/local/bin/k3s kubectl --kubeconfig $cfg"; }
check preflight < "$manifests" || exit 1
k apply -f "$manifests"
for d in $(k get deployment -o name); do
  k rollout status "$d" --timeout=3m || { check diagnose; exit 1; }
done
```

The deploy identity needs `get` on `secrets` in its namespace for the
preflight. It reads no more than it could before: it already makes pods
that mount any Secret there, and reads their logs. Three minutes is enough
for a rollout whose pods start within the app component's minute; a
longer wait only delays the failure.

Pin it like pubkit's workflows, to the commit of a pubdeploy release: the one
`deploy.providers` names, to which `pubkit bump` moves it.

**The app component.** `k8s/components/app` is a kustomize Component with the
hardening and probes every service's app shares. It patches the Deployment
named `app` and its container named `app`, which serves `/healthz` and
`/livez` on the port named `http`, and leaves every other Deployment (a
sign-in proxy, a database) alone:

```yaml
components:
  - https://github.com/Sustenaut/pubdeploy//k8s/components/app?ref=<commit> # vX.Y.Z
```

- The pod runs as user 1000, not root (`runAsNonRoot`), under the runtime's
  seccomp profile, with no API token (`automountServiceAccountToken: false`);
  a token projected for another audience is a volume of its own and is kept.
- The container can't gain privileges, drops every capability and can't
  write its root filesystem, so whatever it writes goes to a volume it mounts
  (an `emptyDir` at `/tmp`, say).
- `startupProbe` waits up to a minute for `/healthz`; `livenessProbe`
  restarts the container after a minute without `/livez`; `readinessProbe`
  sends it requests only while `/healthz` answers. `/livez` should only say
  the process is up; `/healthz` checks what the app can't serve without.

A kustomization's own patches come after its components', so a service that
needs something else (its API token, a longer start) patches it back in its
own `patches`. Pin the component by commit, as above: every service takes it,
so a change to it reaches each one only when that service moves its pin.

## Declaring what a service needs

A service needs more than its manifests before it runs: a namespace, the
Secrets its pods read and what fills them, GitHub secrets and variables for
its deploy, the services it calls, its host in the DNS. pubkit.json's
`deploy` block says so, and `pubdeploy check` checks each, changing
nothing:

```json
"deploy": {
  "namespace": "example",
  "host": "example.example.eu",
  "workflow": "deploy.yml",
  "gate": "DEPLOY_EXAMPLE",
  "overlay": "k8s",
  "needs": [
    {"type": "bitwarden.generated", "name": "example-cookie-secret", "shape": "oauth2-proxy-cookie",
     "secret": {"name": "example-page-secrets", "key": "cookie-secret"}},
    {"type": "k8s.manifests", "path": "k8s/admin/network-policy.yaml"},
    {"type": "upstream", "name": "storage", "health": "https://storage.example.eu/healthz"},
    {"type": "service.health", "path": "/healthz", "job": "cronjob/worker", "after": ["upstream:storage"]}
  ]
}
```

`namespace` is the only key it must have. `workflow` (default `deploy.yml`)
must be in `.github/workflows`, and `overlay` (default `k8s`) must hold a
`kustomization.yaml`. Each need has a `type`, maybe a `name` (each type has a
default; a need's id is `TYPE:NAME`), maybe `after`, the ids it waits for,
and its type's keys; `pubdeploy types` lists them. A need with a `secret`
(`{"name", "key"?, "decode"?: "base64"}`) says it fills that Kubernetes
Secret.

The block and the other blocks imply the rest, so they are not written
twice: the namespace a `k8s.namespace`, a `deploy.rollout` and a
`k8s.secrets-declared`, the host a `dns.site` and a `service.health`, the gate
a `github.gate`; each entry of `secrets` and `github_app` a `github.secret` or
`github.variable`, and the server's settings a `github.deploy-settings`; each
of `variables.names` a `github.variable` that must be set; each need's
`secret`, and each Secret the rendered overlay reads, a `k8s.secret`.

`pubdeploy check` walks them in order: the namespace before what is in
it, what fills a Secret before the Secret, the gate after everything but the
rollout and the service's health. Each is `ready`, `missing`, `drift`,
`blocked` (missing while something it waits for is not ready) or `unknown`
(not checked, refused, or over its time), with what to do about it. It exits
0 when every need is ready, 1 when one is not, and 2 for a bad block.

```
./with-secrets ./pubdeploy check                 # everything, Bitwarden included
./pubdeploy check --offline                      # the manifests and the files only
./pubdeploy check --zones ../infra/pubkit.json   # the hosting block that keeps the zone
./pubdeploy check --json                         # the walk as a deploy-journal/2 document
```

It reads the cluster through `kubectl` (`--kubectl CMD` for another, such as
`k3s kubectl --kubeconfig FILE`), GitHub through `gh`, health addresses over
HTTPS, the DNS through `dig`, and Bitwarden only as `./with-secrets` gives
it: a Bitwarden need is looked for by name in the environment, and is
`unknown` outside with-secrets. It never prints a value: a secret is named,
with its length and kind. `--zones` reads only a file named `pubkit.json`, in
this repository or a checkout beside it, and may be given once per owner whose
zones the units' hosts are in. A host in a zone none of them holds is `unknown`,
not `missing`: its owner's zones were not given.

`pubkit sync --check` checks the block too, and runs the offline walk: every
Secret the manifests read must be one a need fills, with the keys they read,
and every Secret a need fills must be read, so a manifest that reads a new
Secret fails CI until the block says where it comes from. What it cannot
check (no kustomize, a zone kept in another repository) it says, and fails
nothing for.

A package may offer more need types under the entry-point group
`sustenaut.needs`, each `module:object` naming an instance (not a class)
with a `type`, a JSON `schema` of its keys that takes no other, a `grade`, a
`budget` in seconds (at most 10), `offline`, and `default_name`,
`depends_on`, `check` and `fulfil`; and optionally a `fulfil_budget` (at
most 900 seconds, default 60). It need import nothing of pubdeploy's: any
result with `state`, `summary`, `fix` and `details` serves. The walk takes
`type`, `name`, `after` and `unit` out of a need's params, and a `secret` on
any need implies the `k8s.secret` it fills. One pubdeploy cannot use is left
out with a warning. `deploy.providers` names the packages a repository's
needs use, and the managed `./pubdeploy` runs with each:

```json
"providers": [{"distribution": "example-needs", "sha256": "…",
               "wheel": "https://github.com/example-org/example-needs/releases/download/v1.0.0/example_needs-1.0.0-py3-none-any.whl"}]
```

uv does not check a `--with` address's `#sha256`, so `./pubdeploy` fetches each
wheel once into the user's cache and checks it against its sha256 on every
run before uv sees it. `pubkit bump` moves each to its latest release
(pubdeploy's sustenaut.bump hook). A need whose type no installed package offers
names the providers that would.

### Making what a service needs

`pubdeploy walk` is the check (`pubdeploy check` is it without `--fulfil`);
with `--fulfil` it then makes what is missing:

```
./with-secrets ./pubdeploy walk --fulfil --server server.example.eu
./pubdeploy walk --unit other --json
```

It checks every need first, then prints the plan, a line per need it will
act on, and waits for a typed `yes` (`--yes` skips that, for a scheduled
run). It visits the needs in order again: each missing one whose grade is
auto, whose dependencies are ready, is fulfilled and checked again, and
that check is its result, `fulfilled`. A fulfil that fails leaves the need
as it was, with why, and the walk goes on with what does not wait for it.
A Secret that is ready by its keys is made again, and what reads it
restarted, when the walk makes a new value of a need it is made from, such
as a generated secret that was misshapen: otherwise Bitwarden and the
cluster would differ. A propose need is never acted on: its fix is the change to make, such as
the JSON entry and the file it goes in; a human one's is the step. What auto
does, type by type:

| type | its fulfil | it needs |
| --- | --- | --- |
| k8s.namespace | `sustenaut-app NS` on the server | the admin channel |
| k8s.manifests | `kubectl apply -f -` of the file, each object in the namespace it names; its check also runs `kubectl diff --server-side`, so an object there but changed is drift, and a dry run the channel may not make is unknown | kubectl that writes |
| k8s.cronjob, service.health | a Job from the CronJob, waited for; a Job made by hand, NAME-pubkit-... or NAME-now, counts as the CronJob's success, as kubectl does not make it the CronJob's | kubectl that writes |
| github.gate | the gate set on, once every need before it is ready, and the workflow run | gh |
| deploy.rollout | the workflow run on the default branch, and waited for | gh |
| auth.sign-in-client | its Secret made on the server, from the client kept there; or the approval record written into `approvals` | the admin channel |

The seven types that hold a secret's value are
[pubsec](https://github.com/Sustenaut/pubsec)'s: `k8s.secret` (a Secret made
from the values of the needs that fill it, on kubectl's standard input),
`github.secret`, `github.variable` and `github.deploy-settings` (set from
Bitwarden through gh), `bitwarden.secret`, `bitwarden.generated` and
`gcp.service-account-key`. pubsec's README, "Making what a service needs",
says what each checks and does. A repository with a deploy block pins its
own pubsec in `deploy.providers`, and `pubkit bump` moves it to pubsec's
latest release, as it does every provider. pubkit keeps a floor, the oldest
pubsec it works with (`PUBSEC_FLOOR`, which its suite tests): `pubkit sync`
lists the floor where none is listed and moves one below it up, and `sync
--check` fails without one or below it, so `./pubdeploy` always walks with
them. The floor moves only when pubkit needs a newer pubsec, such as for a
change to the provider contract. Where pubsec is not installed, a need of
one of its types says so.

`dns.site`, `storage.tenant` and `github.variable-entry` propose; `upstream`
and `k8s.secrets-declared` have no fulfil. Before it fulfils a need that
wants the Bitwarden write token, at a terminal, the walk calls each
`sustenaut.walk` hook, `prepare(ctx, plan, terminal)`: pubsec's asks for the
token once, at a hidden prompt, and gives the walk its writer, kept only by
the process. pubdeploy itself holds no write token. A walk from GitHub Actions,
or with `--yes` and no terminal, asks for none, and those needs are unknown,
saying so.

### Provider contract

A package that offers need types under `sustenaut.needs`, such as pubsec or
pg-backup, imports nothing of pubdeploy's. A check or a fulfil uses the walk's
Context by these names, which are frozen for providers: changing one is a
breaking change, said in pubdeploy's changelog, with a follow-up in each
provider. `root`, `config`, `block`, `namespace`, `unit`, `channel`
(`admin`, `deploy`, `plain` or `plane`), `kubectl(args, input=None)`,
`server(args, input)`, `gh(method, path, body)`, `send(kind, name, repo,
value, environment)`, `bitwarden_writer` (None, or `.write(name, value,
note)`), `http_get(url, timeout)`, `env`, `now()`, `rendered()`, `offline`,
`slug`, `zones`, `resolve(host, type)`, `values` (by Bitwarden name, bytes),
`types`, `needs`, `results`, `sleep(seconds)` and `dispatched`.

A result is any object with `state`, `summary`, `fix` and `details`, and
optionally `fixable` and `step`. A need has `id`, `type`, `name`, `params`,
`implied_by` and `after`. A type has `type`, `schema`, `grade`, `budget` and
`offline`, and optionally `fulfil_budget`, `singleton`, `default_name`,
`grade_for`, `requires`, `action`, `value`, `secret_keys`, `secret_shape`,
`made_from`, `check` and `fulfil`. Each entry point names an instance, not a
class. A hook under `sustenaut.walk` is a function, `prepare(ctx, plan,
terminal)`, returning a line to print or None.

The channels: with `--server HOST` (or `SUSTENAUT_SERVER`) and no
`--kubectl`, kubectl is `ssh root@HOST k3s kubectl`, and a command can run
on the server: the admin channel, everything a fulfil does. Every command
goes over one SSH connection the walk opens before its first check and
closes at its end (ssh's `ControlMaster`, its socket in a directory only
the user may enter): a new connection over a tailnet takes about a second,
longer than a check's budget. `--kubectl 'ssh
-i KEY deploy@HOST {unit} kubectl-read'` is the server's read-only verb, a
JSON line a call over one connection, in the unit's namespace (`{unit}`):
every write is unknown there, the namespace is judged on the admin channel
only, and a Secret is read by its key names (`secret-keys`) or, on a server
without that verb, by name alone. Any other `--kubectl`, or `kubectl`, is
what its kubeconfig may do. A value moves only on a standard input: never
in an argv, a file, a log or the journal.

`deploy.units` adds units beside the top level's, each with its own
`namespace`, `overlay`, `gate` and `host`; they share the workflow and every
need with no `unit` (`"unit": "other"` scopes one). Each is walked and
journaled on its own; `--unit` walks one. When the workflow calls
k8s-deploy.yml, `pubkit sync --check` fails unless its `deploys` lines and
the units agree, and, from k8s-deploy.yml 0.31.0, unless the workflow
starts on `workflow_run` of main with `actions: read`, and on
`workflow_dispatch`, by which the gate's and the rollout's fulfils run it;
`pubkit bump` rewrites a `push` trigger when it moves that pin across 0.31.0.

`--json` prints a deploy-journal/2 document per unit (a list for more than
one): each need with its grade and whether it was fulfilled. `--journal URL`
(or `PUBKIT_JOURNAL_URL`) also writes it to storage, as a file of the tenant
`plane`, and moves the head `OWNER.REPO.UNIT` (lower case, as storage's head names are) to it, If-Match its
ETag, trying once more when another walk moved it first. The token is
`PUBKIT_STORAGE_TOKEN`, or in GitHub Actions the job's OIDC token for
`PUBKIT_STORAGE_AUDIENCE` (default the address's host). A journal that
could not be written is said, and fails nothing.

pubdeploy's `deploy-check.yml` walks it every 30 minutes, read-only, over the
deploy channel, with the deploy key, host and tailnet secrets k8s-deploy.yml
takes and the environment's read-only `BWS_ACCESS_TOKEN`, with
`--tolerate-unknown`: it fails when a need is missing, drift or blocked, and
a need the job cannot judge, such as a secret its token may not list, stays
unknown in the journal and fails nothing. `pubkit sync` no longer seeds its
caller, `.github/workflows/deploy-check.yml`: the convergence engine walks every
deploy service, and a repository removes its caller once the engine shows it.
And every repository with a `with-secrets.json` gets the managed
`with-secrets`: an older copied script is why `bitwarden.*` needs were
unknown, and `pubkit sync --check` says so.

## Developing

```sh
make venv        # a hash-locked environment, this checkout installed editable
make functional  # the Gherkin suite, with its coverage
make check       # what CI runs
```

The suite walks pubsec's seven need types (a test dependency), so the canary
and the fulfil scenarios cover the whole walk.

## Licence

Apache-2.0.

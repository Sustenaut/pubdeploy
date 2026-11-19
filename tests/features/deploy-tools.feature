Feature: The tools `pubrules deploy check` reaches outside a test's fakes
  kustomize, kubectl, HTTP, dig and git, each given a stand-in, never the
  real one, and the command run whole, as a person runs it.

  Scenario: Render runs kustomize build
    Given a scratch directory
    And only stand-ins are installed
    And a stand-in "kustomize" that prints "kind: ConfigMap"
    When the overlay "k8s" is rendered
    Then the result is:
      """
      kind: ConfigMap

      """
    And "kustomize" was run with arguments matching "build */scratch/k8s"

  Scenario: Render falls back to kubectl kustomize
    Given a scratch directory
    And only stand-ins are installed
    And a stand-in "kubectl" that prints "kind: Secret"
    When the overlay "k8s" is rendered
    Then the result is:
      """
      kind: Secret

      """
    And "kubectl" was run with arguments matching "kustomize */scratch/k8s"

  Scenario: Render says what kustomize said
    Given a scratch directory
    And only stand-ins are installed
    And a stand-in "kustomize" that answers in turn:
      | args | exit | stderr                         |
      | *    | 1    | warning\nError: no such file   |
    When the overlay "k8s" is rendered
    Then the refusal's "message" is "kustomize build k8s failed: Error: no such file"
    And the refusal's "missing_tool" is "false"

  Scenario: Render without either tool
    Given a scratch directory
    And only stand-ins are installed
    When the overlay "k8s" is rendered
    Then it is refused, saying "neither kustomize nor kubectl is installed"
    And the refusal's "missing_tool" is "true"

  Scenario: Render is done once
    Given a scratch directory
    And only stand-ins are installed
    And a stand-in "kustomize" that prints "kind: List"
    When the overlay "k8s" is rendered, twice by one renderer
    Then the result is "["kind: List\n", "kind: List\n"]"
    And "kustomize" was run 1 times

  Scenario: Kubectl runs the command given
    Given a scratch directory
    And only stand-ins are installed
    And a stand-in "k3s"
    When kubectl "k3s kubectl --kubeconfig 'a file'" runs "get namespace example"
    Then the result's "returncode" is "0"
    And "k3s" was run with "kubectl --kubeconfig 'a file' get namespace example"
    And "k3s" was run 1 times

  Scenario: Kubectl that is not there
    Given a scratch directory
    And only stand-ins are installed
    When kubectl "kubectl" runs "get namespace example"
    Then the result's "returncode" is "127"
    And the result's "stderr" is "kubectl did not run (FileNotFoundError)"

  Scenario: Resolve asks dig for addresses
    Given a scratch directory
    And only stand-ins are installed
    And a stand-in "dig" that prints:
      """
      192.0.2.1
      host.example.eu.
      """
    When "example.example.eu" is resolved as "A"
    Then the result is "["192.0.2.1"]"
    And "dig" was run with "+short -q example.example.eu. -t A"

  Scenario: Resolve without dig
    Given a scratch directory
    And only stand-ins are installed
    When "example.example.eu" is resolved as "A"
    Then the result is "null"

  Scenario: Http get
    Given the network answers 200, "ok"
    When "https://example.example.eu/healthz" is fetched
    Then the result is "{"status": 200, "body": "ok"}"

  Scenario: Http get of an error status
    Given the secret "canary-7f3e"
    And the network answers 503, "canary-7f3e"
    When "https://example.example.eu/healthz" is fetched
    Then the result is "{"status": 503, "body": ""}"
    And no secret appears in what it produced

  Scenario Outline: Http get that is not answered
    Given the network fails with a <reason>
    When "https://example.example.eu/healthz" is fetched
    Then the refusal is a "<raised>"

    Examples:
      | reason                 | raised          |
      | TimeoutError           | TimeoutError    |
      | ConnectionRefusedError | ConnectionError |

  Scenario Outline: Slug of origin
    Given a scratch directory
    And a git repository
    And the remote "origin" is "<url>"
    When the repository's slug is read
    Then the result is "<slug>"

    Examples:
      | url                                     | slug                |
      | git@github.com:example-org/example.git  | example-org/example |
      | https://github.com/example-org/example  | example-org/example |

  Scenario: Slug of an origin that is not GitHub's
    Given a scratch directory
    And a git repository
    And the remote "origin" is "https://example.eu/example.git"
    When the repository's slug is read
    Then the result is empty
    And the result has 0 characters

  Scenario: Slug outside a repository
    Given a scratch directory
    When the repository's slug is read
    Then the result is empty
    And the result has 0 characters

  Scenario: Zones come from the config and the zones file
    Given a scratch directory
    And a file "other.json" holding "{"hosting": {"zones": {"example.org": {"sites": {"@": {}}}}}}"
    When the zones of {"hosting": {"zones": {"example.eu": {"sites": {}}}}} and "other.json" are gathered
    Then the result is "["example.eu", "example.org"]"

  Scenario: Without a hosting block or a zones file there are no zones
    When the zones of {} and no zones file are gathered
    Then the result is "null"

  Scenario: Zones come from each zones file one per owner
    Given a scratch directory
    And a file "example.org.json" holding "{"hosting": {"zones": {"example.org": {"sites": {}}}}}"
    And a file "example.net.json" holding "{"hosting": {"zones": {"example.net": {"sites": {}}}}}"
    When the zones of {} and "example.org.json, example.net.json" are gathered
    Then the result is "["example.net", "example.org"]"

  Scenario: The walk takes zones more than once
    Given a scratch directory
    And a file "a/pubrules.json" holding "{}"
    And a file "b/pubrules.json" holding "{}"
    And a file "svc/.keep" holding "a service"
    And a walk that keeps the zones files it is given in "walked.json"
    When pubdeploy runs "walk --zones ../a/pubrules.json --zones ../b/pubrules.json" in "svc"
    Then it succeeds
    And the JSON in "walked.json" is:
      """
      ["a", "b"]
      """

  Scenario: The journal says a walk on a laptop ran there
    Given a scratch directory
    And a file "repo" copied from "tests/fixtures/deploy-app"
    When the service in "repo" is checked offline, in the environment {}
    Then the result's "from" is "laptop"

  Scenario Outline: The journal says where the walk ran, and by whom
    Given a scratch directory
    And a file "repo" copied from "tests/fixtures/deploy-app"
    When the service in "repo" is checked offline, in the environment <env>
    Then the result's "from" is "<origin>"
    And the result's "by" is "<by>"

    Examples:
      | env                                                   | origin  | by       |
      | {"GITHUB_ACTIONS": "true", "GITHUB_ACTOR": "someone"} | actions | someone  |
      | {"PUBRULES_PLANE": "1", "PUBRULES_WALK_BY": "schedule"} | plane | schedule |

  Scenario: A check that returns no result is unknown
    Given a need type "example.odd" whose check returns "ready", not a result
    When its need "one" is checked within its budget
    Then the result's "state" is "unknown"
    And the result's "summary" is "the check returned no result (str)"

  Scenario: Every builtin type is one the registry takes
    When the registry checks every builtin type, pubrules's own as one word
    Then the result is "[]"

  Scenario: A summary is one line of at most 120 characters
    When a result is made whose summary is "a", then a line of "b " and 200 "c"s
    Then the result's "summary" is "a b ccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc…"

  Scenario: The context for tests runs no kubectl
    When the context for tests runs kubectl "get namespace example"
    Then the result's "returncode" is "127"

  Scenario: The context for tests resolves nothing
    When the context for tests resolves "example.example.eu" as "A"
    Then the result is "null"

  Scenario Outline: The context for tests reaches nothing
    When the context for tests <does>
    Then the refusal is a "<raised>"

    Examples:
      | does                                        | raised                 |
      | asks GitHub for "repos/example-org/example" | ApiError               |
      | fetches "https://example.example.eu"        | ConnectionRefusedError |
      | renders the manifests                       | Stop                   |

  Scenario: Deploy check runs whole
    Given a scratch directory
    And the program under test is "pubdeploy"
    And a file "." copied from "tests/fixtures/deploy-app"
    And a file "../infra/pubrules.json" copied from "tests/fixtures/deploy-app/zones.json"
    And the file "zones.json" is removed
    And a stand-in "kustomize" that prints the file "rendered.yaml"
    And the environment sets "PUBRULES_ANY_VERSION" to "1"
    When I run "pubdeploy check --offline --zones ../infra/pubrules.json"
    Then it succeeds
    And it prints "ready   k8s.secrets-declared:example"

  Scenario: Deploy check with a zones file that is not there
    Given a scratch directory
    And the program under test is "pubdeploy"
    And a file "." copied from "tests/fixtures/deploy-app"
    And the file "zones.json" is removed
    And a stand-in "kustomize" that prints the file "rendered.yaml"
    And the environment sets "PUBRULES_ANY_VERSION" to "1"
    When I run "pubdeploy check --offline --zones ../gone/pubrules.json"
    Then the exit code is 2
    And stderr mentions "--zones"

  Scenario Outline: Deploy check reads only a pubrules json beside the repository
    Given a scratch directory
    And the program under test is "pubdeploy"
    And a file "." copied from "tests/fixtures/deploy-app"
    And the environment sets "PUBRULES_ANY_VERSION" to "1"
    When I run "pubdeploy check --offline --zones <path>"
    Then it fails
    And stderr mentions "<why>"

    Examples:
      | path                | why                                  |
      | ../infra/zones.json | must be a repository's pubrules.json |
      | /pubrules.json      | must be in the working directory     |

  Scenario: A provider's results need not be pubdeploy's
    Given a provider's need type "example.database" whose results are its own, missing until it is fulfilled
    When a walk checks its need "one"
    Then the result's "state" is "missing"
    And the result's "summary" is "no database"
    And the result's "fix" is "make it"
    And the result's "details" is "["one"]"

  Scenario: A provider's results of a fulfil need not be pubdeploy's
    Given a provider's need type "example.database" whose results are its own, missing until it is fulfilled
    When a walk checks and fulfils its need "one"
    Then the result's "state" is "ready"
    And the result's "fulfilled" is "true"
    And the result's "details" is "["fulfilled: made the database"]"

  Scenario: A fulfil over its budget is left
    Given a need type "example.slow" whose fulfil takes 0.5 seconds, over its fulfil budget of 0.05 seconds
    When its need "one" is fulfilled within its budget
    Then the result's "state" is "unknown"
    And the result's "summary" is "the fulfil took longer than 0.05 s, and was left"

  Scenario: A fulfil budget over 900 seconds is refused
    When the registry checks the type "k8s.cronjob" with a fulfil budget of 901 seconds
    Then the result includes "its fulfil_budget must be more than 0 and at most 900 seconds"

  Scenario Outline: A journal head is a name storage takes
    When the journal head of "<repository>" and the unit "<unit>" is named
    Then the result is "<head>"

    Examples:
      | repository          | unit | head |
      | Example-Org/example | api-eu | example-org.example.api-eu |
      | Some Owner/Repo     | UUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUU | some-owner.repo.uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu |

  Scenario: A namespace without the deploy kubeconfig is missing over the admin channel
    Given a scratch directory
    And only stand-ins are installed
    And a stand-in "kubectl" that prints "{"metadata": {"name": "x"}}"
    And a stand-in "server" that answers in turn:
      | args | exit |
      | *    | 1    |
    When the need "k8s.namespace:app" is checked over the admin channel of the server "host"
    Then the result's "state" is "missing"
    And the result's "summary" is "namespace app has no deploy kubeconfig (/home/deploy/.kube/app on the server)"
    And the result's "fix" is "ssh root@host sustenaut-app app"
    And "server" was run with "test -f /home/deploy/.kube/app"
    And "server" was run 1 times

  Scenario: Manifests apply each object in its own namespace
    Given a scratch directory
    And only stand-ins are installed
    And a file "admin.yaml" holding:
      """
      kind: ClusterRole
      metadata: {name: reader}
      ---
      kind: RoleBinding
      metadata: {name: read, namespace: one}
      ---
      kind: RoleBinding
      metadata: {name: read, namespace: two}
      ---
      kind: NetworkPolicy
      metadata: {name: only}
      """
    And a stand-in "kubectl" that answers in turn:
      | args      | stdout                 |
      | -n unit * | configured\nconfigured |
      | -n one *  | configured             |
      | -n two *  | configured             |
    When the need "k8s.manifests:admin.yaml" of the path "admin.yaml" is fulfilled in the namespace "unit"
    Then the result's "state" is "ready"
    And the result's "summary" is "applied admin.yaml: 4 objects"
    And "kubectl" was run 3 times
    And "kubectl" was run with "-n unit apply --server-side --force-conflicts -f -"
    And "kubectl" was run with "-n one apply --server-side --force-conflicts -f -"
    And "kubectl" was run with "-n two apply --server-side --force-conflicts -f -"

  Scenario: Manifests give kubectl the objects of each namespace together
    Given a scratch directory
    And only stand-ins are installed
    And a file "admin.yaml" holding:
      """
      kind: ClusterRole
      metadata: {name: reader}
      ---
      kind: RoleBinding
      metadata: {name: read, namespace: one}
      ---
      kind: NetworkPolicy
      metadata: {name: only}
      """
    And a stand-in "kubectl" that reads its input
    When the need "k8s.manifests:admin.yaml" of the path "admin.yaml" is fulfilled in the namespace "unit"
    Then "kubectl" read the input:
      """
      kind: ClusterRole
      metadata:
        name: reader
      ---
      kind: NetworkPolicy
      metadata:
        name: only
      """
    And "kubectl" read the input:
      """
      kind: RoleBinding
      metadata:
        name: read
        namespace: one
      """

  Scenario: Manifests that do not parse are not applied
    Given a scratch directory
    And only stand-ins are installed
    And a file "bad.yaml" holding "kind: ["
    When the need "k8s.manifests:bad.yaml" of the path "bad.yaml" is fulfilled in the namespace "unit"
    Then the result's "state" is "drift"
    And nothing was run

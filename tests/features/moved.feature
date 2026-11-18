Feature: The checks of pubdeploy's code that were in pubrules's test_deploy_sync.py when the walk was pubrules's
  providers.bump, a type no installed package offers, the trigger rewrite,
  pubsec's types without pubsec, the provider contract and the
  sustenaut.walk hook.

  Scenario: Bump moves a provider to its latest release
    Given a scratch directory
    And a file "pubrules.json" holding:
      """
      {"kind": "service", "deploy": {"namespace": "example", "providers": [{"distribution": "example-needs", "wheel": "https://github.com/example-org/example-needs/releases/download/v1.0.0/example_needs-1.0.0-py3-none-any.whl", "sha256": "0000000000000000000000000000000000000000000000000000000000000000"}]}}
      """
    And the latest release of "example-org/example-needs" offers its wheel 1.1.0, of the digest "sha256:1111111111111111111111111111111111111111111111111111111111111111"
    When the providers are bumped
    Then the result is "["updated  pubrules.json (deploy.providers example-needs: 1.1.0)"]"
    And the JSON in "pubrules.json" has "deploy.providers" equal to "[{"distribution": "example-needs", "wheel": "https://github.com/example-org/example-needs/releases/download/v1.1.0/example_needs-1.1.0-py3-none-any.whl", "sha256": "1111111111111111111111111111111111111111111111111111111111111111"}]"

  Scenario: Bump leaves a provider at its latest release
    Given a scratch directory
    And a file "pubrules.json" holding:
      """
      {"kind": "service", "deploy": {"namespace": "example", "providers": [{"distribution": "example-needs", "wheel": "https://github.com/example-org/example-needs/releases/download/v1.1.0/example_needs-1.1.0-py3-none-any.whl", "sha256": "1111111111111111111111111111111111111111111111111111111111111111"}]}}
      """
    And the latest release of "example-org/example-needs" offers its wheel 1.1.0, of the digest "sha256:1"
    When the providers are bumped
    Then the result is "[]"
    And nothing was written

  Scenario: Bump leaves a provider without a sha256 saying so
    Given a scratch directory
    And a file "pubrules.json" holding:
      """
      {"kind": "service", "deploy": {"namespace": "example", "providers": [{"distribution": "example-needs", "wheel": "https://github.com/example-org/example-needs/releases/download/v1.0.0/example_needs-1.0.0-py3-none-any.whl"}]}}
      """
    And GitHub may be asked nothing
    When the providers are bumped
    Then the result is "["left     deploy.providers example-needs: it has no sha256 to move; give it the wheel's sha256"]"
    And nothing was written

  Scenario: A type no installed package offers names the providers
    When the need {"type": "example.database"} is checked against the installed types, with the providers "example-needs"
    Then the result is "["deploy: needs[0]: example.database is no type of need pubdeploy or an installed package offers; it would be example-needs's, of deploy.providers, which ./pubdeploy runs with: run ./pubdeploy, or install example-needs"]"

  Scenario: The trigger check finds a deploy started by push
    Given a scratch directory
    And a file "deploy.yml" holding:
      """
      name: deploy
      on:
        push:
          branches: [main]
        workflow_dispatch: {}
      permissions:
        contents: read
        packages: write
      jobs:
        deploy:
          uses: example-org/pubdeploy/.github/workflows/k8s-deploy.yml@v0.1.0
          with:
            image: ghcr.io/example-org/example
            deploys: |
              k8s example
          secrets: inherit
      """
    When the trigger of "deploy.yml" is checked
    Then the result is:
      """
      ["deploy: deploy.yml calls k8s-deploy.yml, which deploys what a run of main tested, and a walk runs it by hand: under on, have\n  workflow_run: { workflows: [main], types: [completed], branches: [main] }\n  workflow_dispatch: {}\nand\npermissions: { actions: read, contents: read, packages: write }"]
      """

  Scenario: The trigger rewrite satisfies the check
    Given a scratch directory
    And a file "deploy.yml" holding:
      """
      name: deploy
      on:
        push:
          branches: [main]
        workflow_dispatch: {}
      permissions:
        contents: read
        packages: write
      jobs:
        deploy:
          uses: example-org/pubdeploy/.github/workflows/k8s-deploy.yml@v0.1.0
          with:
            image: ghcr.io/example-org/example
            deploys: |
              k8s example
          secrets: inherit
      """
    When the trigger of "deploy.yml" is rewritten
    And the trigger of "deploy.yml" is checked
    Then the result is "[]"
    And the file "deploy.yml" includes "workflow_dispatch" once
    And the file "deploy.yml" holds:
      """
      name: deploy
      on:
        workflow_run: { workflows: [main], types: [completed], branches: [main] }
        workflow_dispatch: {}
      permissions:
        actions: read
        contents: read
        packages: write
      jobs:
        deploy:
          uses: example-org/pubdeploy/.github/workflows/k8s-deploy.yml@v0.1.0
          with:
            image: ghcr.io/example-org/example
            deploys: |
              k8s example
          secrets: inherit
      """

  Scenario: The trigger rewrite adds workflow dispatch
    Given a scratch directory
    And a file "deploy.yml" holding:
      """
      name: deploy
      on:
        push:
          branches: [main]
      permissions:
        contents: read
        packages: write
      jobs:
        deploy:
          uses: example-org/pubdeploy/.github/workflows/k8s-deploy.yml@v0.1.0
          with:
            image: ghcr.io/example-org/example
            deploys: |
              k8s example
          secrets: inherit
      """
    When the trigger of "deploy.yml" is rewritten
    And the trigger of "deploy.yml" is checked
    Then the result is "[]"
    And the file "deploy.yml" holds:
      """
      name: deploy
      on:
        workflow_run: { workflows: [main], types: [completed], branches: [main] }
        workflow_dispatch: {}
      permissions:
        actions: read
        contents: read
        packages: write
      jobs:
        deploy:
          uses: example-org/pubdeploy/.github/workflows/k8s-deploy.yml@v0.1.0
          with:
            image: ghcr.io/example-org/example
            deploys: |
              k8s example
          secrets: inherit
      """

  Scenario Outline: The trigger rewrite takes the short forms
    Given a scratch directory
    And a file "deploy.yml" holding:
      """
      on: <on>
      <permissions>
      jobs:
        d:
          uses: example-org/pubdeploy/.github/workflows/k8s-deploy.yml@v0.1.0
      """
    When the trigger of "deploy.yml" is rewritten
    And the trigger of "deploy.yml" is checked
    Then the result is "[]"

    Examples:
      | on                        | permissions                     |
      | push                      | permissions: { contents: read } |
      | [push, workflow_dispatch] |                                 |

  Scenario: Without pubsec a type of its names it
    When the need {"type": "bitwarden.secret", "name": "x"} is checked against pubdeploy's own types
    Then the result is "["deploy: needs[0]: bitwarden.secret is pubsec's: list pubsec in deploy.providers, as `pubrules sync` does, and run ./pubdeploy, which runs it"]"

  Scenario: Without pubsec the needs of its types name it
    When the needs "k8s.secret:x" and "github.secret:Y" are looked for among pubdeploy's own types
    Then the result is "["deploy: github.secret, k8s.secret are pubsec's, which is not installed: list pubsec in deploy.providers, as `pubrules sync` does, and run ./pubdeploy, which runs it"]"

  # The Context's names a provider may use, which the README lists under
  # "Provider contract": changing one breaks pubsec and pg-backup.
  Scenario Outline: The provider contract is on the context
    When the names a context holds are listed
    Then the result includes "<name>"

    Examples:
      | name             | shown              |
      | root             | `root`             |
      | config           | `config`           |
      | block            | `block`            |
      | namespace        | `namespace`        |
      | unit             | `unit`             |
      | channel          | `channel`          |
      | kubectl          | `kubectl`          |
      | server           | `server(           |
      | gh               | `gh(               |
      | send             | `send(             |
      | bitwarden_writer | `bitwarden_writer` |
      | http_get         | `http_get(         |
      | env              | `env`              |
      | now              | `now(              |
      | rendered         | `rendered(         |
      | offline          | `offline`          |
      | slug             | `slug`             |
      | zones            | `zones`            |
      | resolve          | `resolve(          |
      | values           | `values`           |
      | types            | `types`            |
      | needs            | `needs`            |
      | results          | `results`          |
      | sleep            | `sleep(            |
      | dispatched       | `dispatched`       |

  Scenario Outline: The readme lists the provider contract
    When the README's provider contract is read
    Then the result includes "<shown>"

    Examples:
      | name             | shown              |
      | root             | `root`             |
      | config           | `config`           |
      | block            | `block`            |
      | namespace        | `namespace`        |
      | unit             | `unit`             |
      | channel          | `channel`          |
      | kubectl          | `kubectl`          |
      | server           | `server(           |
      | gh               | `gh(               |
      | send             | `send(             |
      | bitwarden_writer | `bitwarden_writer` |
      | http_get         | `http_get(         |
      | env              | `env`              |
      | now              | `now(              |
      | rendered         | `rendered(         |
      | offline          | `offline`          |
      | slug             | `slug`             |
      | zones            | `zones`            |
      | resolve          | `resolve(          |
      | values           | `values`           |
      | types            | `types`            |
      | needs            | `needs`            |
      | results          | `results`          |
      | sleep            | `sleep(            |
      | dispatched       | `dispatched`       |

  Scenario: A walk hook that fails is said and the walk goes on
    Given the secret "canary-7f3e"
    And a walk hook "broken" that fails, saying "the token is canary-7f3e"
    And a walk hook "says" that gives the context the writer "a writer", saying "a line"
    When the walk is prepared
    Then stderr mentions "pubdeploy: deploy: the sustenaut.walk hook broken failed (ValueError)"
    And stderr mentions "a line"
    And the result is "a writer"
    And no secret appears in what it produced

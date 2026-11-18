Feature: What pubrules calls of pubdeploy (hooks.py), and that pubdeploy imports nothing of pubrules's

  Scenario Outline: The hooks are offered under their groups
    When pubdeploy's entry points in the group "<group>" are listed
    Then the result is "["<hook>"]"

    Examples:
      | group          | hook                  |
      | sustenaut.sync | pubdeploy.hooks:check |
      | sustenaut.bump | pubdeploy.hooks:bump  |

  Scenario: Pubdeploy imports nothing of pubrules
    When every module of pubdeploy is imported with pubrules blocked
    Then it succeeds

  Scenario Outline: Without a deploy block the sync hook says nothing
    Given a scratch directory
    When the sync hook is <mode> {"kind": "utility"}
    Then the result is "[[], false]"
    And nothing was written

    Examples:
      | mode     |
      | checking |
      | syncing  |

  Scenario Outline: The sync hook seeds no scheduled walk
    Given a scratch directory
    And the offline check of the deploy block finds nothing
    When the sync hook is <mode> {"kind": "service", "deploy": {"namespace": "example"}}
    Then the result is "[[], false]"
    And the file ".github" does not exist
    And nothing was written

    Examples:
      | mode     |
      | checking |
      | syncing  |

  Scenario Outline: A disagreement is said, and fails only a check
    Given a scratch directory
    And the offline check of the deploy block finds "pubdeploy: deploy: drift"
    And a file ".github/workflows/deploy-check.yml" holding "kept"
    When the sync hook is <mode> {"kind": "service", "deploy": {"namespace": "example"}}
    Then the result is "[["pubdeploy: deploy: drift"], <fails>]"
    And the file ".github/workflows/deploy-check.yml" holds "kept"

    Examples:
      | mode     | fails |
      | checking | true  |
      | syncing  | false |

  Scenario: Bump moves pubdeploy's workflows to the release the providers name
    Given a service whose providers list pubdeploy 0.2.0, deployed on:
      """
      workflow_run: { workflows: [main], types: [completed], branches: [main] }
      workflow_dispatch: {}
      """
    And GitHub reads the tag "v0.2.0" of Sustenaut/pubdeploy as the commit "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    When pubdeploy's workflows are bumped
    Then the result is:
      """
      [
        "updated  .github/workflows/deploy-check.yml (pubdeploy@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa # v0.2.0)",
        "updated  .github/workflows/deploy.yml (pubdeploy@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa # v0.2.0)"
      ]
      """
    And the file ".github/workflows/deploy.yml" includes "k8s-deploy.yml@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa # v0.2.0"
    And the file ".github/workflows/deploy-check.yml" includes "deploy-check.yml@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa # v0.2.0"

  Scenario: Bump rewrites a deploy started by push
    Given a service whose providers list pubdeploy 0.2.0, deployed on:
      """
      push: { branches: [main] }
      """
    And GitHub reads the tag "v0.2.0" of Sustenaut/pubdeploy as the commit "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    When pubdeploy's workflows are bumped
    Then the file ".github/workflows/deploy.yml" does not include "push:"
    And the file ".github/workflows/deploy.yml" includes "workflow_run: { workflows: [main]"
    And the file ".github/workflows/deploy.yml" includes "workflow_dispatch: {}"
    And the file ".github/workflows/deploy.yml" includes "actions: read"

  Scenario: Bump pins by tag when the tag cannot be read
    Given a service whose providers list pubdeploy 0.2.0, deployed on:
      """
      workflow_run: { workflows: [main] }
      workflow_dispatch: {}
      """
    And GitHub answers no request
    When pubdeploy's workflows are bumped
    Then the file ".github/workflows/deploy-check.yml" includes "deploy-check.yml@v0.2.0"

  Scenario: Bump without pubdeploy in providers moves no workflow
    Given a scratch directory
    And a file "pubrules.json" holding "{"kind": "service", "deploy": {"namespace": "example"}}"
    And GitHub reads the tag "v0.2.0" of Sustenaut/pubdeploy as the commit "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    When pubdeploy's workflows are bumped
    Then the result is "[]"
    And nothing was written

  Scenario: Deploy ssh passes its own tests
    Given a scratch directory
    And a file "deploy-ssh" copied from "actions/deploy-ssh"
    When I run "bash deploy-ssh/test.sh"
    Then it succeeds

Feature: Each unit's Secret for its live runs' Job, which pubrules sync adds
  A live run's Job runs in the unit's namespace with the Secret pubdeploy-executor as its
  environment. A unit with bitwarden.* needs checks and fulfils them with a Bitwarden
  token, so the Secret holds BWS_ACCESS_TOKEN, filled by a bitwarden.secret need named
  <unit>-executor-bws-token: the unit's own token of the read account. sync --check fails
  without it, and sync adds it, changing nothing else of pubrules.json. A unit no Job
  walks says "executor": false.

  Scenario: sync --check fails for a unit with Bitwarden needs and no executor token
    Given a scratch directory
    And the offline check of the deploy block finds nothing
    And a file "pubrules.json" holding:
      """
      {"kind": "service", "deploy": {"namespace": "example", "needs": [{"type": "bitwarden.secret", "name": "example-key", "secret": {"name": "example", "key": "key"}}]}}
      """
    When the sync hook checks pubrules.json
    Then the hook fails, saying:
      """
      pubdeploy: deploy: unit example has bitwarden.* needs and no need filling the Secret pubdeploy-executor's BWS_ACCESS_TOKEN, which its live runs' Job reads Bitwarden with; run `pubrules sync`, which adds the bitwarden.secret example-executor-bws-token, or say "executor": false for a unit no Job walks
      """
    And the file "pubrules.json" holds:
      """
      {"kind": "service", "deploy": {"namespace": "example", "needs": [{"type": "bitwarden.secret", "name": "example-key", "secret": {"name": "example", "key": "key"}}]}}
      """

  Scenario: sync adds the need last, the rest of pubrules.json as it was, and a check then passes
    Given a scratch directory
    And the offline check of the deploy block finds nothing
    And a file "pubrules.json" holding:
      """
      {
        "kind": "service",
        "deploy": {
          "namespace": "example",
          "needs": [
            {"type": "bitwarden.secret", "name": "example-key", "secret": {"name": "example", "key": "key \"[one]\""}}
          ]
        }
      }
      """
    When the sync hook syncs pubrules.json
    Then the hook succeeds, saying:
      """
      updated  pubrules.json (deploy.needs bitwarden.secret:example-executor-bws-token, the Secret pubdeploy-executor's BWS_ACCESS_TOKEN)
      """
    And the file "pubrules.json" holds:
      """
      {
        "kind": "service",
        "deploy": {
          "namespace": "example",
          "needs": [
            {"type": "bitwarden.secret", "name": "example-key", "secret": {"name": "example", "key": "key \"[one]\""}},
            {"type": "bitwarden.secret", "name": "example-executor-bws-token", "secret": {"name": "pubdeploy-executor", "key": "BWS_ACCESS_TOKEN"}}
          ]
        }
      }
      """
    When the sync hook checks pubrules.json
    Then the hook succeeds, saying nothing

  Scenario: Each unit gets its own need, scoped to it, and a unit already filled none
    Given a scratch directory
    And the offline check of the deploy block finds nothing
    And a file "pubrules.json" holding:
      """
      {"kind": "service", "deploy": {"namespace": "example", "units": {"other": {"namespace": "example-other"}, "third": {"namespace": "example-third"}}, "needs": [{"type": "bitwarden.generated", "name": "example-cookie", "shape": "hex-32", "secret": {"name": "example", "key": "cookie"}}, {"type": "bitwarden.secret", "name": "own-token", "unit": "third", "secret": {"name": "pubdeploy-executor", "key": "BWS_ACCESS_TOKEN"}}]}}
      """
    When the sync hook syncs pubrules.json
    Then the hook succeeds, saying:
      """
      updated  pubrules.json (deploy.needs bitwarden.secret:example-executor-bws-token, the Secret pubdeploy-executor's BWS_ACCESS_TOKEN)
      updated  pubrules.json (deploy.needs bitwarden.secret:other-executor-bws-token, the Secret pubdeploy-executor's BWS_ACCESS_TOKEN)
      """
    And the file "pubrules.json" holds:
      """
      {"kind": "service", "deploy": {"namespace": "example", "units": {"other": {"namespace": "example-other"}, "third": {"namespace": "example-third"}}, "needs": [{"type": "bitwarden.generated", "name": "example-cookie", "shape": "hex-32", "secret": {"name": "example", "key": "cookie"}}, {"type": "bitwarden.secret", "name": "own-token", "unit": "third", "secret": {"name": "pubdeploy-executor", "key": "BWS_ACCESS_TOKEN"}}, {"type": "bitwarden.secret", "name": "example-executor-bws-token", "secret": {"name": "pubdeploy-executor", "key": "BWS_ACCESS_TOKEN"}, "unit": "example"}, {"type": "bitwarden.secret", "name": "other-executor-bws-token", "secret": {"name": "pubdeploy-executor", "key": "BWS_ACCESS_TOKEN"}, "unit": "other"}]}}
      """

  Scenario Outline: A unit that needs no executor token is left as it is
    Given a scratch directory
    And the offline check of the deploy block finds nothing
    And a file "pubrules.json" holding:
      """
      {"kind": "service", "deploy": <block>}
      """
    When the sync hook checks pubrules.json
    Then the hook succeeds, saying nothing

    Examples:
      | case                                    | block                                                                                                                                                                                             |
      | it says executor false                  | {"namespace": "example", "executor": false, "needs": [{"type": "bitwarden.secret", "name": "k", "secret": {"name": "example", "key": "k"}}]}                                                       |
      | it has no Bitwarden needs               | {"namespace": "example", "needs": [{"type": "upstream", "name": "storage"}]}                                                                                                                      |
      | its Bitwarden needs are another unit's  | {"namespace": "example", "units": {"other": {"namespace": "example-other", "executor": false}}, "needs": [{"type": "bitwarden.secret", "name": "k", "unit": "other", "secret": {"name": "o", "key": "k"}}]} |
      | the token comes another way             | {"namespace": "example", "needs": [{"type": "bitwarden.generated", "name": "k", "shape": "hex-32", "secret": {"name": "pubdeploy-executor", "key": "BWS_ACCESS_TOKEN"}}]}                         |
      | the block is the offline check's to say | {"namespace": "example", "needs": {"type": "bitwarden.secret"}}                                                                                                                                   |

  Scenario: The top level's executor false is its unit's alone
    Given a scratch directory
    And the offline check of the deploy block finds nothing
    And a file "pubrules.json" holding:
      """
      {"kind": "service", "deploy": {"namespace": "example", "executor": false, "units": {"other": {"namespace": "example-other"}}, "needs": [{"type": "bitwarden.secret", "name": "k", "secret": {"name": "example", "key": "k"}}]}}
      """
    When the sync hook checks pubrules.json
    Then the hook fails, saying:
      """
      pubdeploy: deploy: unit other has bitwarden.* needs and no need filling the Secret pubdeploy-executor's BWS_ACCESS_TOKEN, which its live runs' Job reads Bitwarden with; run `pubrules sync`, which adds the bitwarden.secret other-executor-bws-token, or say "executor": false for a unit no Job walks
      """

  Scenario: A pubrules.json the text edit cannot keep is written whole
    Given a scratch directory
    And the offline check of the deploy block finds nothing
    And a file "pubrules.json" holding:
      """
      {"notes": {"deploy": {"needs": []}}, "kind": "service", "deploy": {"namespace": "example", "needs": [{"type": "bitwarden.secret", "name": "k", "secret": {"name": "example", "key": "k\"]"}}]}}
      """
    When the sync hook syncs pubrules.json
    Then the file "pubrules.json" holds:
      """
      {
        "notes": {
          "deploy": {
            "needs": []
          }
        },
        "kind": "service",
        "deploy": {
          "namespace": "example",
          "needs": [
            {
              "type": "bitwarden.secret",
              "name": "k",
              "secret": {
                "name": "example",
                "key": "k\"]"
              }
            },
            {
              "type": "bitwarden.secret",
              "name": "example-executor-bws-token",
              "secret": {
                "name": "pubdeploy-executor",
                "key": "BWS_ACCESS_TOKEN"
              }
            }
          ]
        }
      }
      """

  Scenario: An empty needs list takes the need as its only one
    When the need for the unit "example" is put into the pubrules.json text {"deploy": {"namespace": "example", "needs": []}}
    Then the result is:
      """
      {"deploy": {"namespace": "example", "needs": [{"type": "bitwarden.secret", "name": "example-executor-bws-token", "secret": {"name": "pubdeploy-executor", "key": "BWS_ACCESS_TOKEN"}}]}}
      """

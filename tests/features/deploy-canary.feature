Feature: The canary: no secret value ever reaches what pubdeploy prints
  Every fake
  Secret value, every fake Bitwarden value, the write token, every fake key
  JSON and what the deploy channel shows of a Secret hold CANARY, and every
  value a fulfil generates is kept as one too. Each test drives the checks,
  and the fulfils, through a state where values are read, judged, generated
  and moved, and what comes out (stdout, stderr, the journal, any
  exception's text, and every argv kubectl, ssh, gcloud or gh was given)
  must not hold one: a value moves on a standard input only. This test must
  never be weakened: a check or a fulfil that needs to show a value is
  wrong, not the test.

  Scenario Outline: No value is printed, in any state, by any command
    Given the deploy world with <state>
    When pubdeploy runs "<command>"
    Then no value is printed, passed to a program or kept in the journal

    Examples:
      | state                                         | command                    |
      | GitHub forbidden                              | check                      |
      | GitHub forbidden                              | check --json               |
      | GitHub forbidden                              | check --offline --json     |
      | GitHub forbidden                              | walk --fulfil --yes        |
      | GitHub forbidden                              | walk --fulfil --yes --json |
      | GitHub without its secrets                    | check                      |
      | GitHub without its secrets                    | check --json               |
      | GitHub without its secrets                    | check --offline --json     |
      | GitHub without its secrets                    | walk --fulfil --yes        |
      | GitHub without its secrets                    | walk --fulfil --yes --json |
      | a Secret without its key                      | check                      |
      | a Secret without its key                      | check --json               |
      | a Secret without its key                      | check --offline --json     |
      | a Secret without its key                      | walk --fulfil --yes        |
      | a Secret without its key                      | walk --fulfil --yes --json |
      | a bad cookie in Bitwarden                     | check                      |
      | a bad cookie in Bitwarden                     | check --json               |
      | a bad cookie in Bitwarden                     | check --offline --json     |
      | a bad cookie in Bitwarden                     | walk --fulfil --yes        |
      | a bad cookie in Bitwarden                     | walk --fulfil --yes --json |
      | a bad cookie in the cluster                   | check                      |
      | a bad cookie in the cluster                   | check --json               |
      | a bad cookie in the cluster                   | check --offline --json     |
      | a bad cookie in the cluster                   | walk --fulfil --yes        |
      | a bad cookie in the cluster                   | walk --fulfil --yes --json |
      | a key Bitwarden refuses                       | check                      |
      | a key Bitwarden refuses                       | check --json               |
      | a key Bitwarden refuses                       | check --offline --json     |
      | a key Bitwarden refuses                       | walk --fulfil --yes        |
      | a key Bitwarden refuses                       | walk --fulfil --yes --json |
      | a key to make                                 | check                      |
      | a key to make                                 | check --json               |
      | a key to make                                 | check --offline --json     |
      | a key to make                                 | walk --fulfil --yes        |
      | a key to make                                 | walk --fulfil --yes --json |
      | a variable that differs from Bitwarden        | check                      |
      | a variable that differs from Bitwarden        | check --json               |
      | a variable that differs from Bitwarden        | check --offline --json     |
      | a variable that differs from Bitwarden        | walk --fulfil --yes        |
      | a variable that differs from Bitwarden        | walk --fulfil --yes --json |
      | all well                                      | check                      |
      | all well                                      | check --json               |
      | all well                                      | check --offline --json     |
      | all well                                      | walk --fulfil --yes        |
      | all well                                      | walk --fulfil --yes --json |
      | kubectl forbidden                             | check                      |
      | kubectl forbidden                             | check --json               |
      | kubectl forbidden                             | check --offline --json     |
      | kubectl forbidden                             | walk --fulfil --yes        |
      | kubectl forbidden                             | walk --fulfil --yes --json |
      | kubectl refusing writes                       | check                      |
      | kubectl refusing writes                       | check --json               |
      | kubectl refusing writes                       | check --offline --json     |
      | kubectl refusing writes                       | walk --fulfil --yes        |
      | kubectl refusing writes                       | walk --fulfil --yes --json |
      | no cookie in Bitwarden, nor its Secret        | check                      |
      | no cookie in Bitwarden, nor its Secret        | check --json               |
      | no cookie in Bitwarden, nor its Secret        | check --offline --json     |
      | no cookie in Bitwarden, nor its Secret        | walk --fulfil --yes        |
      | no cookie in Bitwarden, nor its Secret        | walk --fulfil --yes --json |
      | nothing in the cluster                        | check                      |
      | nothing in the cluster                        | check --json               |
      | nothing in the cluster                        | check --offline --json     |
      | nothing in the cluster                        | walk --fulfil --yes        |
      | nothing in the cluster                        | walk --fulfil --yes --json |
      | nothing reachable                             | check                      |
      | nothing reachable                             | check --json               |
      | nothing reachable                             | check --offline --json     |
      | nothing reachable                             | walk --fulfil --yes        |
      | nothing reachable                             | walk --fulfil --yes --json |
      | outside with-secrets                          | check                      |
      | outside with-secrets                          | check --json               |
      | outside with-secrets                          | check --offline --json     |
      | outside with-secrets                          | walk --fulfil --yes        |
      | outside with-secrets                          | walk --fulfil --yes --json |
      | over the deploy channel                       | check                      |
      | over the deploy channel                       | check --json               |
      | over the deploy channel                       | check --offline --json     |
      | over the deploy channel                       | walk --fulfil --yes        |
      | over the deploy channel                       | walk --fulfil --yes --json |
      | over the deploy channel, before secret-keys   | check                      |
      | over the deploy channel, before secret-keys   | check --json               |
      | over the deploy channel, before secret-keys   | check --offline --json     |
      | over the deploy channel, before secret-keys   | walk --fulfil --yes        |
      | over the deploy channel, before secret-keys   | walk --fulfil --yes --json |

  Scenario: An exception holding a value is not shown
    Given the example service
    And the secret "canary-7f3e"
    And a need type "example.leaky" whose check raises, saying "the value is canary-7f3e"
    When its need "one" is walked
    Then the result's "needs.0.state" is "unknown"
    And the result's "needs.0.summary" is "the check failed (ValueError)"
    And no secret appears in what it produced

  Scenario: A value in the rendered manifests is not shown
    Given the example service
    And the secret "canary-7f3e"
    And the rendered manifests hold the Secret "example-held"
    When I run pubdeploy "check" "--offline"
    Then it succeeds
    And no secret appears in what it produced

  Scenario: Every result of the sound fixture is free of values
    Given the example service
    And the secret "canary-7f3e"
    When the example service's needs are walked
    Then the result's "results" is "["Result"]"
    And no secret appears in what it produced

  Scenario: A fulfil that raises holding a value is not shown
    Given the example service
    And the secret "canary-7f3e"
    And a need type "example.leaky" whose fulfil raises, saying "the value is canary-7f3e"
    When its need "one" is walked and fulfilled
    Then the result's "needs.0.state" is "missing"
    And the result's "needs.0.details.0" is "fulfil failed: the fulfil failed (ValueError); this is a fault in example.leaky's fulfil: report it"
    And no secret appears in what it produced

  Scenario: Generated values stay in the walk
    Given the example service
    And Bitwarden has no "example-cookie-secret"
    When I run pubdeploy "walk" "--fulfil" "--yes" "--json"
    Then it succeeds
    And Bitwarden was given a value the walk generated for "example-cookie-secret"
    And no output holds a value

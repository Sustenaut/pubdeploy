Feature: A unit's needs as a state machine, which the convergence engine runs live
  `pubdeploy machine` prints the unit's needs as XState v5 JSON: a parallel region per
  need, waiting, checking, found, fulfilling, ready, failed, blocked and stopped, each
  need after the needs it waits for. The deploy block's run section may only narrow
  what is generated. `walk --need` walks only the named needs, which is how a live run
  walks each. The same machine runs alike in python-statemachine and in XState.

  Scenario: The generated default puts every need in default_mode, with its after-edges, 4 at a time
    Given the needs "k8s.namespace:a", "k8s.secret:s" after "k8s.namespace:a", and "upstream:u"
    When the machine is compiled
    Then it validates
    And every region is in mode "fulfil", and the machine runs 4 at a time
    And the region "k8s_secret_s" is after "k8s_namespace_a"
    And the region "upstream_u" is after nothing

  Scenario: A run section narrows: a need's mode, an added after-edge, fewer at a time
    Given the needs "k8s.namespace:a", "k8s.secret:s" after "k8s.namespace:a", and "upstream:u"
    And the run section {"schema": 1, "default_mode": "fulfil", "parallel": 2, "needs": {"upstream:u": {"mode": "check", "after": ["k8s.secret:s"]}}}
    When the machine is compiled
    Then it validates
    And the region "upstream_u" is in mode "check", and its found state is final
    And the region "upstream_u" is after "k8s_secret_s"
    And the machine runs 2 at a time

  Scenario Outline: A run section that widens is refused, saying why
    Given the needs "k8s.namespace:a", "k8s.secret:s" after "k8s.namespace:a", and "upstream:u"
    And the run section <section>
    When the run section is checked
    Then the problem is "<said>"

    Examples:
      | section                                                                           | said                                                         |
      | {"schema": 1, "parallel": 8}                                                      | deploy.run.parallel may only lower the default: 1 to 4, not 8 |
      | {"schema": 1, "needs": {"github.gate:x": {"mode": "check"}}}                      | deploy.run.needs names github.gate:x, which is no need of this unit |
      | {"schema": 1, "needs": {"k8s.namespace:a": {"after": ["k8s.secret:s"]}}}          | deploy.run.needs' after-edges make needs wait for each other |
      | {"schema": 1, "needs": {"upstream:u": {"mode": "always"}}}                        | deploy.run.needs.upstream:u.mode must be check or fulfil     |
      | {"schema": 1, "needs": {"upstream:u": {"after": ["nowhere:x"]}}}                  | deploy.run.needs.upstream:u is after nowhere:x, which is no need of this unit |
      | {"schema": 1, "needs": {"upstream:u": {"skip": true}}}                            | deploy.run.needs.upstream:u has no setting skip; it takes mode, after |
      | {"default_mode": "fulfil"}                                                        | deploy.run must give "schema": 1                             |
      | {"schema": 2}                                                                     | deploy.run's schema 2 is newer than this pubdeploy's (1)      |
      | {"schema": 1, "default_mode": "both"}                                             | deploy.run.default_mode must be check or fulfil              |
      | {"schema": 1, "extra": 1}                                                         | deploy.run has no setting extra                              |

  Scenario: A serial kind's needs are chained one after the other
    Given the needs "pg.database:one", "pg.database:two" and "pg.database:three" of a serial kind
    When the machine is compiled
    Then the region "pg_database_two" is after "pg_database_one"
    And the region "pg_database_three" is after "pg_database_two"

  Scenario: Needs touching one resource are chained
    Given the needs "bitwarden.generated:c" and "bitwarden.secret:t", both filling the Secret "page"
    When the machine is compiled
    Then the region "bitwarden_secret_t" is after "bitwarden_generated_c"

  Scenario: A human need never fulfils, and a need that continues on Stop says why
    Given the needs "k8s.jwks:keys" graded human, and "deploy.rollout:r" that continues on Stop, warning "the workflow keeps running"
    When the machine is compiled
    Then it validates
    And the region "k8s_jwks_keys" never enters fulfilling
    And the region "deploy_rollout_r" stops with "continue", warning "the workflow keeps running"

  Scenario: A machine that is not one pubdeploy makes is refused, saying why
    Then a machine whose region goes to a state it lacks, or continues on Stop without a warning, does not validate

  Scenario Outline: python-statemachine and XState v5 run the machine alike
    Given the needs "k8s.namespace:a", "k8s.secret:s" after "k8s.namespace:a", and "upstream:u"
    And every need in mode "<mode>"
    When the script "<script>" drives the machine in python-statemachine and in XState v5
    Then both give the same states after each event
    And the last states are <last>

    Examples:
      | mode   | script                     | last                                                                    |
      | check  | check-only, all clean      | k8s_namespace_a ready, k8s_secret_s ready, upstream_u ready              |
      | fulfil | a failed fulfil blocks its dependant | k8s_namespace_a failed, k8s_secret_s blocked, upstream_u ready |
      | fulfil | Stop in the middle         | k8s_namespace_a stopped, k8s_secret_s stopped, upstream_u ready           |

  Scenario: pubdeploy machine prints the example's machine, which validates
    Given the example service
    When I run pubdeploy "machine"
    Then it succeeds
    And it prints a machine that validates, with a region for "service.health:example" after "upstream_storage"

  Scenario: pubdeploy machine takes a mode for every need, and a need's own
    Given the example service
    When I run pubdeploy "machine" "--mode" "check" "--modes" "upstream:storage=fulfil"
    Then it succeeds
    And it prints a machine with "service.health:example" in mode "check" and "upstream:storage" in mode "fulfil"

  Scenario: A run section sync --check refuses fails the deploy block's check
    Given the example service
    And the deploy block's "run" is {"schema": 1, "parallel": 9}
    When I run pubdeploy "sync-check" "--check"
    Then the exit code is 1
    And stderr mentions "deploy.run.parallel may only lower the default"

  Scenario: walk --need refuses a need whose predecessor is not ready, and walks nothing more
    Given the example service
    And "https://storage.example.eu/healthz" answers 503
    When I run pubdeploy "walk" "--need" "service.health:example"
    Then the exit code is 2
    And stderr mentions "--need service.health:example waits for upstream:storage, which is not ready"

  Scenario: walk --need with --fulfil checks and fulfils only the named needs
    Given the example service
    And the Secret "example-files" is not in the cluster
    And the Secret "example-app-env" is not in the cluster
    And the CronJob "worker" never succeeded
    When I run pubdeploy "walk" "--fulfil" "--yes" "--need" "k8s.secret:example-files" "--need" "upstream:storage"
    Then it succeeds
    And it prints only "k8s.secret:example-files" and "upstream:storage"
    And "k8s.secret:example-files" is ready, "(fulfilled)"
    And kubectl made no Job and no other Secret than "example-files"

  Scenario: walk --need names a need the unit has
    Given the example service
    When I run pubdeploy "walk" "--need" "upstream:nowhere"
    Then the exit code is 2
    And stderr mentions "--need upstream:nowhere is no need of this unit"

  Scenario: --budget-seconds shortens a check's budget
    Given the example service
    And the "upstream" check takes 1 second
    When I run pubdeploy "check" "--need" "upstream:storage" "--budget-seconds" "0.2"
    Then "upstream:storage" is unknown, "longer than 0.2 s"

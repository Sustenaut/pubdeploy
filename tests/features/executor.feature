Feature: A live run's needs, walked by pubdeploy's executor outside the convergence engine
  `pubdeploy executor --engine URL --run ID` reads the run with the run's own token,
  walks each need with `pubdeploy walk --need` once every need it comes after has ended,
  as many at once as the run's machine allows, and reports each move to the engine as an
  event numbered by the need's own sequence. A Stop acts on each walking need as its stop
  class says; a person may cancel one by name. It exits 0 once every need has ended, 3
  when the engine refuses it and 1 when the engine cannot be reached, and reports its exit.

  Scenario: Needs that wait for nothing walk at once; one walks once those it comes after are ready
    Given a running run with the needs "a", "b" and "c" after "a"
    And every walk finds its need ready
    When the executor walks the run
    Then it exits 0
    And "a" and "b" were walked at the same time
    And "c" was walked only after "a" was ready
    And every need ended "ready"
    And its last event reports exit 0

  Scenario: The run's parallel caps how many needs walk at once
    Given a running run with the needs "a", "b" and "c", 1 at a time
    And every walk finds its need ready
    When the executor walks the run
    Then it exits 0
    And no two walks ran at the same time

  Scenario: A need found missing is fulfilled, then checked again
    Given a running run with the need "a"
    And the check of "a" finds it missing, and its fulfil leaves it ready
    When the executor walks the run
    Then "a" moved waiting, checking, found, fulfilling, checking, ready
    And its fulfil was walked with --fulfil --yes and its budget

  Scenario: A need still found after its fulfil fails, as fulfilled but not ok
    Given a running run with the need "a"
    And every walk of "a" finds it missing
    When the executor walks the run
    Then "a" ended "failed", saying "still found after its fulfil"
    And the event that failed it is not ok

  Scenario: A need in mode check that is found ends found, and is not fulfilled
    Given a running run with the need "a" in mode check
    And every walk of "a" finds it missing
    When the executor walks the run
    Then "a" moved waiting, checking, found
    And no walk was given --fulfil

  Scenario: A need after one that failed is blocked and never walks
    Given a running run with the needs "a", "b" and "c" after "a"
    And the walk of "a" prints no journal
    When the executor walks the run
    Then "a" ended "failed", saying "the walk printed no journal"
    And "c" ended "blocked", saying "did not end ready"
    And "c" was never walked

  Scenario: A walk past its budget and the grace is ended, and its need fails
    Given a running run with the need "a" of a 0.1 s budget
    And the walk of "a" never ends
    When the executor walks the run
    Then "a" ended "failed", saying "it ran past its budget"

  Scenario: A Stop ends each walking need as its stop class says, and starts nothing more
    Given a running run with the needs "sig" stopping by signal, "short" that shortens, "cont" that continues, and "later" after "cont"
    And every walk waits until it is told to end
    When the executor walks the run, and a person presses Stop while all three walk
    Then "sig" ended "stopped", saying "stopped (signal)"
    And "short" was told its budget had ended, and ended "unknown"
    And "cont" ended "ready"
    And "later" ended "stopped", saying "before it started"
    And it exits 0

  Scenario: A person cancels a need that continues on Stop, by its name
    Given a running run with the needs "cont" that continues, and "other"
    And every walk waits until it is told to end
    When the executor walks the run, and a person presses Stop and cancels "cont"
    Then "cont" ended "stopped", saying "cancelled"

  Scenario: An event the engine refuses ends the executor with exit 3, and its exit is reported
    Given a running run with the need "a"
    And every walk finds its need ready
    And the engine refuses the event that moves "a" to "ready"
    When the executor walks the run
    Then it exits 3
    And its last event reports exit 3

  Scenario: A run that is not running is not walked
    Given an awaiting run with the need "a"
    When the executor walks the run
    Then it exits 3
    And no walk ran

  Scenario: A lost answer is posted again as the same event, which the engine keeps once
    Given the engine answers the first POST of an event with 502
    When an event is posted to the engine over HTTP
    Then it was posted twice, the same event both times, with the run's token as the bearer
    And the executor waited before it posted again

  Scenario: An engine that never answers ends the executor with exit 1
    Given the engine never answers
    When the executor walks the run over HTTP
    Then it exits 1

  Scenario: The engine's refusal over HTTP is said
    Given the engine answers every call with 403 "not-this-runs-executor"
    When the executor walks the run over HTTP
    Then it exits 3
    And it said "403 not-this-runs-executor"
    And it read the run at "http://engine/runs/r1/executor" with the run's token

  Scenario: A walk is never given the run's token
    Given a running run with the need "a"
    And every walk finds its need ready
    And PUBDEPLOY_RUN_TOKEN is set
    When the executor walks the run
    Then no walk's environment holds PUBDEPLOY_RUN_TOKEN

  Scenario: The executor needs the run's token
    Given the program under test is "pubdeploy"
    When I run "pubdeploy executor --engine http://engine.invalid --run r1"
    Then the exit code is 2
    And stderr mentions "PUBDEPLOY_RUN_TOKEN is not set"

  Scenario: An executor started again goes on where the run's journal leaves it
    Given a running run with the needs "a", "b" and "c" after "a"
    And every walk finds its need ready
    And the run's journal already moved "a" to "ready" by its events 1 and 2
    When the executor walks the run
    Then "a" was never walked
    And "b" moved waiting, checking, ready
    And "c" was walked only after "a" was ready

  Scenario: A walk that cannot start fails its need, and the others go on
    Given a running run with the needs "a", "b" and "c", 4 at a time
    And every walk finds its need ready
    And the walk of "a" cannot start
    When the executor walks the run
    Then "a" ended "failed", saying "its walk could not run (OSError)"
    And "b" ended "ready"
    And it exits 0

  Scenario Outline: A walk's journal says where it leaves the need
    When the walk of "a" prints <stdout>
    Then the need is judged "<state>", saying "<said>"

    Examples:
      | stdout                                                                                       | state  | said                                      |
      | {"schema": "deploy-journal/2", "needs": [{"id": "a", "state": "drift", "details": ["Secret x: key k differs"]}]} | found  | Secret x: key k differs |
      | {"schema": "deploy-journal/2", "needs": [{"id": "b", "state": "ready"}]}                      | failed | the walk's journal does not name the need |
      | [{"schema": "deploy-journal/2", "needs": [{"id": "a", "state": "odd", "summary": "hm"}]}]    | failed | odd: hm                                   |
      | not json                                                                                     | failed | the walk printed no journal (exit 1)      |

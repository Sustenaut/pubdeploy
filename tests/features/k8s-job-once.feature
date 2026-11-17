Feature: k8s.job-once runs a one-off Job once, and says how it went
  A backfill, a migration or a seed is one Job, run once: made from a CronJob's
  template or a manifest, with the need's arguments added. The Job stays as the
  record that it ran. A failed one is made again only with rerun: if-failed, and
  the plan says which Job that deletes. The fulfil makes the Job and returns; the
  next walk sees whether it is running, completed or failed.

  Background:
    Given the namespace "integrations" has the CronJob "ci-jobs", whose job runs "python -m poll"
    And the need {"type": "k8s.job-once", "name": "ci-jobs-backfill", "cronjob": "ci-jobs", "args": ["--since-days", "90"], "timeout": "6h"}

  Scenario Outline: The check reads the Job's state
    Given the Job "ci-jobs-backfill" <state>
    When the need is checked
    Then it is <result>, saying "<said>"

    Examples:
      | state           | result  | said                                    |
      | is not there    | missing | Job ci-jobs-backfill has not run        |
      | is running      | unknown | Job ci-jobs-backfill is running         |
      | completed       | ready   | Job ci-jobs-backfill completed at       |
      | has a condition Complete | ready | Job ci-jobs-backfill completed  |
      | failed          | drift   | Job ci-jobs-backfill failed             |

  Scenario: A running Job is not acted on, and a failed one only with rerun: if-failed
    Given the Job "ci-jobs-backfill" is running
    When the need is checked
    Then the walk would not act on it
    Given the Job "ci-jobs-backfill" failed
    When the need is checked
    Then the walk would not act on it
    And its fix says "give the need rerun: if-failed"

  Scenario: The fulfil makes the Job from the CronJob's template, with the arguments, and returns
    Given the Job "ci-jobs-backfill" is not there
    When the need is checked
    And the plan's line is asked for
    Then the line is "create Job ci-jobs-backfill in namespace integrations from CronJob ci-jobs with the arguments --since-days 90"
    When the need is fulfilled
    Then it is ready, saying "made Job ci-jobs-backfill from CronJob ci-jobs: the next walk sees how it went"
    And kubectl made the Job "ci-jobs-backfill" running "python -m poll --since-days 90", for 21600 seconds at most, kept after it ends
    And kubectl deleted nothing

  Scenario: A failed Job with rerun: if-failed is deleted, and only it, then made again
    Given the need also says "rerun" is "if-failed"
    And the Job "ci-jobs-backfill" failed
    When the need is checked
    And the plan's line is asked for
    Then the line is "delete Job ci-jobs-backfill in namespace integrations (no data is deleted), then create Job ci-jobs-backfill in namespace integrations from CronJob ci-jobs with the arguments --since-days 90"
    When the need is fulfilled
    Then it is ready, saying "made Job ci-jobs-backfill"
    And kubectl deleted the Job "ci-jobs-backfill" alone
    And kubectl made the Job "ci-jobs-backfill" running "python -m poll --since-days 90", for 21600 seconds at most, kept after it ends

  Scenario: A failed Job without rerun is never deleted by a fulfil
    Given the Job "ci-jobs-backfill" failed
    When the need is checked
    And the need is fulfilled
    Then it is drift, saying "the need does not run it again"
    And kubectl deleted nothing
    And kubectl made no Job

  Scenario: The Job waits for its CronJob, which the deploy applies
    Given the namespace "integrations" has no CronJob "ci-jobs"
    And the Job "ci-jobs-backfill" is not there
    When the need is checked
    Then it is missing, saying "CronJob ci-jobs is not in integrations yet"
    And the walk would not act on it

  Scenario: A Job from a manifest takes the manifest's Job, named as the need
    Given the file "k8s/seed.yaml" holds a Job whose container runs "seed"
    And the need is {"type": "k8s.job-once", "name": "seed-once", "manifest": "k8s/seed.yaml", "args": ["--all"]}
    And the Job "seed-once" is not there
    When the need is checked
    Then it is missing, saying "Job seed-once has not run"
    When the need is fulfilled
    Then kubectl made the Job "seed-once" running "seed --all", with no deadline, kept after it ends

  Scenario Outline: A manifest that is not one Job is said, and nothing is made
    Given the file "k8s/seed.yaml" <holds>
    And the need is {"type": "k8s.job-once", "name": "seed-once", "manifest": "k8s/seed.yaml"}
    And the Job "seed-once" is not there
    When the need is fulfilled
    Then it is drift, saying "<said>"
    And kubectl made no Job

    Examples:
      | holds                                   | said                                    |
      | holds two Jobs                          | holds 2 Jobs, not one                   |
      | is not there                            | cannot be read as a Job                 |
      | holds a Job with no container           | gives a Job with no container           |

  Scenario Outline: A need with both sources, or neither, is said
    Given the need is <need>
    When the need is checked
    Then it is drift, saying "<said>"

    Examples:
      | need                                                                                             | said                                 |
      | {"type": "k8s.job-once", "name": "x", "cronjob": "ci-jobs", "manifest": "k8s/seed.yaml"}         | names both of cronjob and manifest   |
      | {"type": "k8s.job-once", "name": "x"}                                                            | names neither of cronjob and manifest |

  Scenario Outline: What kubectl refuses is said, and leaves the need as it was
    Given the Job "ci-jobs-backfill" is not there
    And kubectl refuses to <verb>
    When the need is <done>
    Then it is <result>, saying "<said>"

    Examples:
      | verb              | done      | result  | said                                    |
      | read Jobs         | checked   | unknown | kubectl may not read jobs               |
      | read CronJobs     | checked   | unknown | kubectl may not read cronjobs           |
      | read CronJobs     | fulfilled | missing | CronJob ci-jobs could not be read       |
      | create            | fulfilled | missing | Job ci-jobs-backfill could not be made  |

  Scenario: A Job kubectl will not delete is not made again
    Given the need also says "rerun" is "if-failed"
    And the Job "ci-jobs-backfill" failed
    And kubectl refuses to delete
    When the need is checked
    And the need is fulfilled
    Then it is missing, saying "Job ci-jobs-backfill could not be deleted"
    And kubectl made no Job

  Scenario: pubdeploy lists the type
    Then the types pubdeploy has include "k8s.job-once", graded auto, needing kubectl that writes

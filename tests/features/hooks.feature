Feature: What pubrules calls of pubdeploy (hooks.py), and that pubdeploy imports nothing of pubrules's

  Scenario: The hooks are offered under their groups
    Then the hooks are offered under their groups

  Scenario: Pubdeploy imports nothing of pubrules
    Then pubdeploy imports nothing of pubrules

  Scenario: Without a deploy block the sync hook says nothing
    Then without a deploy block the sync hook says nothing

  Scenario: The sync hook seeds no scheduled walk
    Then the sync hook seeds no scheduled walk

  Scenario: Writing a disagreement is said and fails nothing
    Then writing a disagreement is said and fails nothing

  Scenario: Bump moves pubdeploys workflows to the release providers names
    Then bump moves pubdeploys workflows to the release providers names

  Scenario: Bump rewrites a deploy started by push
    Then bump rewrites a deploy started by push

  Scenario: Bump pins by tag when the tag cannot be read
    Then bump pins by tag when the tag cannot be read

  Scenario: Bump without pubdeploy in providers moves no workflow
    Then bump without pubdeploy in providers moves no workflow

  Scenario: Deploy ssh passes its own tests
    Then deploy ssh passes its own tests

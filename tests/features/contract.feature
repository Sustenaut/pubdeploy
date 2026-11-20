Feature: The provider contract
  pubdeploy.contract holds what a provider of need types or walk hooks may
  rely on: the Context's names, a need's, a result's and a type's, and the
  checks the walk makes of a type and a hook as it loads them. README's
  "Provider contract" lists the same names, and this suite walks with a
  stand-in provider built from the contract alone, never with pubsec.

  Scenario: The Context has every name of the contract
    When the contract's Context names the walk's Context lacks are gathered
    Then the result is empty

  Scenario: A need and a result have every name of the contract
    When the contract's need and result names the walk's Need and Result lack are gathered
    Then the result is empty

  Scenario: README lists the contract's names, and no others
    When the names README's "Provider contract" lists, and the contract's, are compared
    Then the result is empty

  Scenario: The contract imports nothing of the walk
    When the modules of pubdeploy that pubdeploy.contract imports are gathered
    Then the result is "['pubdeploy.model']"

  Scenario: The stand-in's types are need types by the contract
    When the stand-in's types are checked by the contract
    Then the result is empty

  Scenario: The stand-in reads only the contract's names of a Context
    When the names the stand-in reads from a Context, and not in the contract, are gathered
    Then the result is empty

  Scenario: The stand-in's hook is a walk hook by the contract
    When the stand-in's hook is checked by the contract
    Then the result is empty

  Scenario Outline: A hook that is not one is named
    When a hook that <is> is checked by the contract
    Then the result is "<said>"

    Examples:
      | is                     | said                                    |
      | takes two arguments    | ['it must take (ctx, plan, terminal)']  |
      | is not a function      | ['it is not a function']                |

  Scenario: The suite imports nothing of pubsec
    When this suite's imports of pubsec are gathered
    Then the result is empty

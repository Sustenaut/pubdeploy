Feature: The tools `pubkit deploy check` reaches outside a test's fakes
  kustomize, kubectl, HTTP, dig and git, each given a stand-in, never the
  real one, and the command run whole, as a person runs it.

  Scenario: Render runs kustomize build
    Then render runs kustomize build

  Scenario: Render falls back to kubectl kustomize
    Then render falls back to kubectl kustomize

  Scenario: Render says what kustomize said
    Then render says what kustomize said

  Scenario: Render without either tool
    Then render without either tool

  Scenario: Render is done once
    Then render is done once

  Scenario: Kubectl runs the command given
    Then kubectl runs the command given

  Scenario: Kubectl that is not there
    Then kubectl that is not there

  Scenario: Resolve asks dig for addresses
    Then resolve asks dig for addresses

  Scenario: Resolve without dig
    Then resolve without dig

  Scenario: Http get
    Then http get

  Scenario: Http get of an error status
    Then http get of an error status

  Scenario: Http get that is not answered
    Then http get that is not answered

  Scenario: Slug of origin
    Then slug of origin

  Scenario: Slug outside a repository
    Then slug outside a repository

  Scenario: Zones come from the config and the zones file
    Then zones come from the config and the zones file

  Scenario: Zones come from each zones file one per owner
    Then zones come from each zones file one per owner

  Scenario: The walk takes zones more than once
    Then the walk takes zones more than once

  Scenario: The journal says where the walk ran
    Then the journal says where the walk ran

  Scenario: A check that returns no result is unknown
    Then a check that returns no result is unknown

  Scenario: Every builtin type is one the registry takes
    Then every builtin type is one the registry takes

  Scenario: A summary is one line of at most 120 characters
    Then a summary is one line of at most 120 characters

  Scenario: The context for tests reaches nothing
    Then the context for tests reaches nothing

  Scenario: Deploy check runs whole
    Then deploy check runs whole

  Scenario: Deploy check reads only a pubkit json beside the repository
    Then deploy check reads only a pubkit json beside the repository

  Scenario: A providers result need not be pubkits
    Then a providers result need not be pubkits

  Scenario: A fulfil over its budget is left
    Then a fulfil over its budget is left

  Scenario: A fulfil budget over 900 seconds is refused
    Then a fulfil budget over 900 seconds is refused

  Scenario: A journal head is a name storage takes
    Then a journal head is a name storage takes

  Scenario: A namespace without the deploy kubeconfig is missing over the admin channel
    Then a namespace without the deploy kubeconfig is missing over the admin channel

  Scenario: Manifests apply each object in its own namespace
    Then manifests apply each object in its own namespace

  Scenario: Manifests that do not parse are not applied
    Then manifests that do not parse are not applied

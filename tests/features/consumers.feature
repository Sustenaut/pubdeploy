Feature: pubdeploy names no repository that consumes it
  What identifies a consumer lives on the consumer's side, in its pubkit.json.
  pubdeploy, its tests and its example service may name example hosts, the
  tools' and registries' hosts, pubkit and pubdeploy, and the names the
  deploy workflow and the server's program already use.

  Scenario: pubdeploy, its tests and its example service name no consumer
    When I scan pubdeploy's files for consumers' names
    Then it finds none

  Scenario Outline: The deploy guard finds a consumer's name, however it is written
    Given a deploy file reads "<text>"
    When I scan it for consumers' names
    Then it finds "<found>"

    Examples:
      | text                                         | found                 |
      | "host": "app.some-owner.eu"                  | app.some-owner.eu     |
      | upstream at https://files.some-owner.com/x   | files.some-owner.com  |
      | the Sustenaut storage                        | Sustenaut             |
      | as schryer runs it                           | schryer               |

  Scenario Outline: The deploy guard lets examples, tools and the deploy settings through
    Given a deploy file reads "<text>"
    When I scan it for consumers' names
    Then it finds nothing

    Examples:
      | text                                                  |
      | "host": "example.example.eu"                          |
      | https://storage.example.eu/healthz                    |
      | image: quay.io/oauth2-proxy/oauth2-proxy and ghcr.io  |
      | SUSTENAUT_SERVER, SUSTENAUT_DEPLOY_SSH_KEY            |
      | the sustenaut.needs group, and sustenaut-app          |
      | https://github.com/Sustenaut/pubdeploy/blob/main/x.json |
      | https://github.com/Sustenaut/pubkit/blob/main/x.json  |

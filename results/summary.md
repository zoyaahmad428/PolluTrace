# Phase 1 results
## Reproduction (135 IDoFT OD victims attempted)
| Status | Victims |
|---|---|
| reproduced | 90 |
| build_failed | 25 |
| not_reproduced | 20 |

| Project | Victims | Reproduced | JDK | Build (min) | Other outcomes |
|---|---|---|---|---|---|
| Activiti | 17 | 0 | - | - | build_failed 17 |
| Struts | 22 | 4 | 8 | 5.3 | not_reproduced 18 |
| admiral | 1 | 1 | 8 | 6.1 | - |
| aismessages | 2 | 2 | 8 | 0.6 | - |
| c2mon | 1 | 1 | 8 | 5.8 | - |
| cukes | 1 | 1 | 8 | 1.0 | - |
| dropwizard | 1 | 0 | - | - | build_failed 1 |
| elastic-job-lite | 2 | 2 | 8 | 2.5 | - |
| hadoop | 1 | 0 | - | - | build_failed 1 |
| http-request | 25 | 25 | 8 | 0.7 | - |
| incubator-dubbo | 10 | 9 | 17 | 0.6 | not_reproduced 1 |
| jhipster-registry | 2 | 1 | 8 | 11.7 | not_reproduced 1 |
| marine-api | 12 | 12 | 8 | 1.6 | - |
| openpojo | 3 | 0 | - | - | build_failed 3 |
| riptide | 1 | 0 | - | - | build_failed 1 |
| spring-boot | 8 | 8 | 8 | 9.5 | - |
| spring-data-envers | 2 | 0 | - | - | build_failed 2 |
| spring-ws | 2 | 2 | 11 | 1.0 | - |
| wikidata-toolkit | 2 | 2 | 8 | 0.5 | - |
| wildfly | 20 | 20 | 11 | 11.9 | - |

Median time per single-JVM order: alone 1.0 s, polluter->victim 1.3 s.

## Order sensitivity of unpatched dev victims (N = 100 random orders)
| ID | Victim | Fail rate | First failing order | s/order | Total s |
|---|---|---|---|---|---|
| V034 | Jsr286DispatcherTest#testProcessAction_ok | 0.17 | 1 | 2.7 | 271.9 |
| V110 | DirectoryManagerFactoryTest#createDefaultDirectoryManagerPath | 0.42 | 1 | 1.12 | 114.4 |
| V114 | RequestBrokerKubernetesServiceTest#testRequestStateHasK8sInfo | 0 | 0.667 | 2 | 428.9 |
| V051 | TagConfigDocumentIndexerTests#reindexTagConfigDocuments | 0 | 0.19 | 2 | 43.3 |
| V090 | AbstractAISMessageListenerTest#testSequenceListenerWithMixedOrder | 0 | 0.35 | 1 | 0.31 |
| V112 | NMEAMessageHandlerTest#canHandleUnfragmentedMessageReceived | 0 | 0.77 | 1 | 0.37 |
| V055 | FailoverServiceTest#assertGetLocalFailoverItemsIfShutdown | 0 | 0.62 | 1 | 4.01 |
| V070 | HttpRequestTest#verifierAccepts | 0 | 0.54 | 1 | 6.31 |
| V127 | InitialContextTestCase#testRegisterURLSchemeHandler | 0 | 0.16 | 9 | 1.14 |
| V052 | HttpAssertionFacadeImplTest#shouldReturnBodyWhenEnabledAndNoMax | 0 | 0.2 | 9 | 3.77 |
| V057 | AccountResourceTest#testGetUnknownAccount | 0 | 0.629 | 1 | 26.2 |
| V108 | SpringDigestPasswordValidationCallbackHandlerTest#testAuthenticateUserDigestValidInvalid | 0 | 0.34 | 3 | 2.53 |
| V024 | ChangeTelnetHandlerTest#testChangeServiceNotExport | 0 | 0.25 | 1 | 120.85 |
| V100 | CloudFoundryWebFluxEndpointIntegrationTests#operationWithSecurityInterceptorSuccess | 0 | 0.5 | 2 | 15.55 |
| V041 | Jsr168DispatcherTest#testRender_ok | 0 | 0.1 | 25 | 1.95 |

Median fail rate 0.0; minimum 0.0; median 2.0 s per order.

Probability that N random orders expose a patch that still fails at rate p: 1-(1-p)^N

| N | p=0.0 | p=0.05 | p=0.1 | min/victim |
|---|---|---|---|---|
| 1 | 0.000 | 0.050 | 0.100 | 0.0 |
| 5 | 0.000 | 0.226 | 0.410 | 0.2 |
| 10 | 0.000 | 0.401 | 0.651 | 0.3 |
| 20 | 0.000 | 0.642 | 0.878 | 0.7 |
| 50 | 0.000 | 0.923 | 0.995 | 1.7 |
| 100 | 0.000 | 0.994 | 1.000 | 3.3 |

## B1 single LLM call (15 dev victims)
| Outcome | Victims |
|---|---|
| fixed | 8 |
| not_fixed | 4 |
| compile_error | 2 |
| no_code_in_reply | 1 |

Fix rate (passes after polluter): 8/15 = 53.3%. Accepted: 8; false fixes under 100 random orders: 0/8 = 0.0%. First failing order of false fixes: []. Median time per victim 510.2 s (of which random-order revalidation 471.0 s). Median tokens per victim 4684.0; model gemini-3.8-flash.

## B2 iFixFlakies (15 dev victims)
| Outcome | Victims |
|---|---|
| tool_error | 8 |
| timeout | 5 |
| fixed | 1 |
| not_fixed | 1 |

Fix rate (passes after polluter): 1/15 = 6.7%. Median time per victim 769.8 s.


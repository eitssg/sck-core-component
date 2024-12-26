# Security engine

## Scenarios
The example in this section are scenarios which should be handled by the security engine

### Instance able to perform default actions
(Instance -> Role) -> action

### Instance able to invoke a Lambda
(Instance -> Role) -> Lambda
- Action: invoke
  Source: my-app

### S3 able to invoke a Lambda
S3 -> (Lambda permission -> Lambda)
- Action: invoke
  Source: my-s3

### SNS able to invoke a Lambda
SNS -> (Lambda permission -> Lambda)
- Action: invoke
  Source: my-sns-topic

### SNS able to publish to SQS
SNS -> (Queue policy -> SQS)
- Action: write
  Source: my-sns-topic

### Instance able to publish to SQS
(Instance -> Role) -> SQS
- Action: write
  Source: my-app

### SG able to transfer to other SG
(SG -> outbound rule) -> (inbound rule -> SG)
- Action: TCP:22
  Source: my-app

## Cross-app security

Identify components by qualified references, eg: prn:pipeline:region:account:portfolio:app:branch:build:component

    Pipeline::Security:
      - Allow: TCP:443
        Source: prn:pipeline:*:*:demo:demoapp1:master:*:app
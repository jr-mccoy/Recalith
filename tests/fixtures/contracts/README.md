# Shared contract wire fixtures

`envelopes/valid/*.json` must be accepted and `envelopes/invalid/*.json` rejected by
the strict Pydantic `EventEnvelope`. Task 3b's generated standard-library wire
validator (`recalith.fast`) must reach the same verdict on every file
(`test_fast_and_strict_validation_agree`). Each file is `{"description", "envelope"}`;
`nonfinite_number.json` deliberately contains a bare `NaN` token.

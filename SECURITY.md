# Security Policy

## Supported Releases

Only the latest published development release receives security fixes. No
current release is a production-safety certification.

## Reporting

Do not open a public issue for vulnerabilities that could expose credentials,
private evaluation material, evaluator keys, sealed worlds, or a reliable
scoring bypass. Use GitHub private vulnerability reporting for the repository.

Include:

- affected release and artifact hash;
- minimal reproduction;
- expected and observed behavior;
- whether evaluator secrets or candidate isolation were crossed;
- whether the issue can create a false safe, false verified, or hidden external
  effect result.

Do not include live credentials or real customer data. Synthetic reproductions
are sufficient.

## Security Boundaries

The evaluator owns world state, oracle state, source readback, hard counters,
and sealed material. Candidate agents receive only the declared adapter
protocol. Advisory LLM review never changes official hard scores.

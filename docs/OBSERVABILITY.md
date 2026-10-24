<!-- devbox-conventions docs__OBSERVABILITY.md v6 BEGIN — generated; edit outside the markers -->
## Observability: logs, metrics, errors, health and security events

Every app and every machine on this network reports what it is doing in one
language. This document is that language, not a product choice: it names no
collector, no dashboard and no ticketing system, because replacing any of them
must not require changing a single producer.

A project adopting this needs to know nothing about what consumes the output. If
you find yourself writing a field because a particular consumer wants it, the
field belongs in that consumer's configuration, not here.

If a project emits nothing — a library, a template, a repository of documents —
declare it rather than leaving this unrendered; see "Declaring this out of scope"
at the end.

### One event per line, and the line is structured

Every log record is a single line of JSON. One event per line, no multi-line
records, no pretty-printing. A stack trace is a single string field with escaped
newlines, not several lines.

Required on every record, with these exact names:

    timestamp               RFC 3339 in UTC, milliseconds, e.g. 2026-10-08T05:21:33.482Z
    severity_text           one of the scale below
    severity_number         its number from the scale below
    service.name            the service, stable across deployments
    service.version         the build it came from
    deployment.environment  dev | staging | prod
    body                    the human-readable message

Required when the record belongs to a request or an operation that has one:

    trace_id                32 hex characters
    span_id                 16 hex characters

The names are the OpenTelemetry semantic conventions' names, taken rather than
invented, because the one thing a common language cannot afford is a per-project
spelling of `service.name`. Anything beyond these is yours, and goes in whatever
shape you like, but DO NOT re-spell the required ones: a consumer joining on
`service.name` cannot find `serviceName`, and the failure is silent — the record
arrives, the join misses, and the service looks idle.

Correlation when there is no trace: an operation that is not part of a trace
still carries a `correlation_id` that is constant for the operation and appears
on every record it produces. A record no other record can be grouped with is a
record nobody can follow.

### The severity scale is fixed

    severity_text  severity_number  what it means
    TRACE          1                not enabled outside development
    DEBUG          5                diagnostic, off by default in prod
    INFO           9                normal, expected, worth keeping
    WARN           13               recovered, or degraded, and continuing
    ERROR          17               this operation failed
    FATAL          21               the process cannot continue

Two rules about the scale, both of which exist because they are broken by
accident:

INFO IS NOT A DUMPING GROUND. If every record is INFO, severity carries no
information and a consumer cannot alert on anything. A request that succeeded is
INFO; a request that failed for the caller's reasons — a 4xx — is WARN at most;
a request that failed for yours is ERROR.

AND A HANDLED ERROR IS STILL AN ERROR. Catching an exception and logging WARN
because the process survived loses the one event somebody needed to see. The
severity describes the OPERATION's outcome, not the process's.

### Where it goes is configuration, never compiled in

One endpoint per environment, by configuration only:

    OTEL_EXPORTER_OTLP_ENDPOINT   base URL of the collector
    OTEL_EXPORTER_OTLP_HEADERS    credentials, if the endpoint needs them
    OTEL_SERVICE_NAME             overrides service.name when set

OTLP over HTTP is the transport. A producer that cannot speak OTLP — a shell
script, a cron job, a machine's own daemons — writes to syslog with RFC 5424
structured data, or to journald, and something at the machine level forwards it.
The format above still applies: the fields go in the structured-data element, or
in a JSON message, and not into prose a consumer has to parse back out.

RUNNING WITH NO ENDPOINT CONFIGURED IS VALID AND IS NOT A DEGRADED MODE. With no
endpoint, records go to standard output and the app works. This is the same
standalone-or-networked rule the identity convention states, and for the same
reason: a project that cannot run without the network is a project nobody can
develop on a train. An app MUST NOT fail to start, block a request, or lose a
record because a collector is unreachable; emitting is best-effort and never on
the critical path.

NEVER COMPILE IN AN ENDPOINT, not even a default pointing at this network. A
hostname in a binary is a hostname in every copy of that binary, including the
ones running somewhere else.

### Health: two endpoints that answer different questions

    GET /healthz    LIVENESS   is this process alive and not wedged
    GET /readyz     READINESS  should this process receive traffic now

Both answer in under a second, require no authentication, and are excluded from
request logging — a liveness probe every two seconds is not an event.

    200  {"status":"ok"}
    503  {"status":"unready","checks":{"database":"fail","migrations":"ok"}}

LIVENESS MUST NOT CHECK DEPENDENCIES. A liveness probe that fails because the
database is down gets the process killed and restarted, which does not fix the
database and does remove the one thing that could have served cached answers or
reported the outage. Liveness answers: can this process still run code.

READINESS IS WHERE DEPENDENCIES BELONG, and `ready` has one meaning: every
dependency this process needs to serve a request is reachable AND every schema
migration it requires has been applied. A process that is up and mid-migration
is NOT ready, and saying otherwise is how a half-migrated instance serves
errors.

### Metrics: one endpoint and a minimum set

    GET /metrics    OpenMetrics / Prometheus text format

The minimum every service reports:

    http_server_request_duration_seconds   histogram, labelled by route and status
    http_server_requests_total             counter, labelled by route and status
    http_server_errors_total               counter, 5xx only

LABEL BY ROUTE, NEVER BY PATH. `/persons/by-email` is a route; `/persons/12345`
is a path, and labelling by it gives a metric one series per person — an
unbounded label set that eventually takes the collector down. Route labels are a
fixed, small set known at build time. The same rule forbids labelling by user id,
by session, by query, or by anything a caller chooses.

A job rather than a service reports, per run:

    job_last_run_timestamp_seconds    gauge, when it last started
    job_last_success_timestamp_seconds gauge, when it last succeeded
    job_duration_seconds              gauge or histogram
    job_runs_total                    counter, labelled by outcome

The two timestamps are what make "it has not run" answerable. A counter alone
cannot distinguish a job that never fails from a job that never runs.

### Errors: structured, deduplicable, and stripped

An application error report carries, beyond the required log fields:

    exception.type        the class or kind
    exception.message     the message, with no interpolated data (see below)
    exception.stacktrace  one string, newlines escaped
    error.fingerprint     a stable grouping key the producer chooses

The fingerprint is what makes a thousand occurrences one row rather than a
thousand. Fingerprint on the SHAPE of the error — the type plus the code site —
never on its data, or every distinct input becomes a separate issue and the
consumer becomes a log viewer with extra steps.

Reports are sent to the configured endpoint in the Sentry protocol's envelope
form when the producer has a client for it, and as ERROR-severity log records
otherwise. Both are acceptable; a producer MUST NOT invent a third.

WHAT AN ERROR REPORT MUST NOT CONTAIN — and this is the same list as for logs,
stated again here because error paths are where it leaks:

- the request body, the response body, or any field from either;
- the query string, in whole or in part;
- headers, except a strict allowlist that excludes `Authorization`, `Cookie`
  and `Set-Cookie`;
- any credential, token, key, session identifier or password, including ones
  that are expired or wrong;
- the value that failed validation.

THE LAST ONE IS THE EASIEST TO MISS AND HAS ALREADY HAPPENED HERE. A validation
failure that echoes the rejected value to tell the caller what was wrong puts
exactly the data the caller typed into every record and every error report —
person-db's 422 answers did this, and the fix was to name the FIELD and the RULE
instead (orbit 20261008-032). Say `email: must be a valid address`, never
`email: 'someone@example.com' is not valid`.

### Security events: a fixed vocabulary, spelled the same everywhere

This is the section that matters most, and the reason it matters is that a
security question is asked across apps, not inside one. "Did this account fail
to log in anywhere last night" is answerable only if every app spells the event
the same way. One app with its own spelling is one blind spot, and a blind spot
nobody knows about.

The vocabulary is CLOSED. These are the names, in `event.name`:

<!-- `conventions check` READS THE BLOCK BELOW and asserts it names the same set
     of events as docs/OBSERVABILITY.vocabulary.json, in both directions. The
     extraction starts after the line containing "The vocabulary is CLOSED" and
     stops at the line containing "Every security event carries", then takes the
     first word of each indented line. It is bounded that way because the field
     list further down also contains dotted names (`event.name`, `user.id`,
     `session.id`) and an unbounded scan would read six field names as events.
     If you reformat this block — a table, different indentation, a blank line
     between entries — update vocab_prose_names() in the conventions tool in the
     same change, or the check goes VACUOUS and says so rather than passing. -->

    auth.login.success        a credential was accepted and a session began
    auth.login.failure        a credential was rejected
    auth.logout               a session was ended deliberately
    auth.token.refused        a presented token was invalid, expired or unknown
    authz.denied              an authenticated principal was refused an action
    authz.role.change         a role, group or permission was granted or removed
    admin.action              a privileged operation was performed
    ratelimit.hit             a caller was throttled

Every security event carries, in addition to the required log fields:

    event.name          from the list above, exactly
    event.outcome       success | failure
    user.id             the PSEUDONYMOUS id — see the next section
    client.address      the source address as the app saw it
    user_agent.original the client's user agent, when there is one
    session.id          a per-session random id, never the session token itself

And per event, additionally:

    auth.login.failure    error.reason   a CODE, not prose: bad_credentials |
                          unknown_user | locked | mfa_required | mfa_failed
    auth.token.refused    error.reason   expired | signature | audience |
                          issuer | revoked | malformed
    authz.denied          action, resource.type, resource.id, and the
                          permission or role that was required
    authz.role.change     target user.id, the role, and granted|revoked
    admin.action          action, resource.type, resource.id
    ratelimit.hit         the limit's name and its window

`error.reason` IS A CODE BECAUSE PROSE CANNOT BE COUNTED. "Did failures shift
from bad_credentials to mfa_failed this week" is a question about a fixed set;
against free text it is a question about string matching.

AND A FAILURE MUST NOT SAY WHICH HALF WAS WRONG in anything the caller can see.
`unknown_user` and `bad_credentials` are both legitimate in the LOG, where they
are the difference between a typo and an enumeration attempt; the ANSWER to the
caller is the same either way. Logging the distinction is good; returning it is
an account-enumeration oracle.

Security events are emitted at INFO when they succeed and WARN when they fail,
with one exception: `authz.denied` and `authz.role.change` are INFO either way,
because a refusal is the control working and a role change is always worth
keeping.

THESE EVENTS ARE NOT OPTIONAL AND NOT SAMPLED. Whatever sampling a producer
applies to ordinary logs, security events are always emitted, because the
interesting one is rare by definition.

### Jobs and backups: absence has to be detectable

Anything that runs on a schedule reports three things in the common format:

    job.start     when it began, with job.name and the run's correlation_id
    job.success   when it finished, with job.duration_ms and a count of whatever
                  it processed
    job.failure   when it did not, with the error fields above

The counts matter as much as the outcome. A backup that succeeds having copied
zero bytes is a successful backup of nothing, and `job.success` alone cannot
tell you — which is the same empty-selector failure that this network's tooling
has hit repeatedly. Report what it did, not only that it ended.

A JOB THAT DOES NOT RUN EMITS NOTHING, so nothing in this document detects it.
That is deliberate and is the consumer's job: a schedule is declared somewhere a
consumer can read, and the alert is on the ABSENCE of `job.success` within the
expected window. What the producer owes is a `job.name` that is stable and a
schedule that is written down — an alert on absence cannot be built against a
job whose name changes with its version.

### Personal data, secrets, and the two things that leak

NO PERSONAL DATA IN LOGS, BEYOND A STABLE PSEUDONYMOUS USER ID. No names, no
email addresses, no phone numbers, no addresses, no dates of birth, no free text
a person typed. `user.id` is an opaque, stable identifier — the app's own local
id, or a hash — and never the email, never the username, never the subject claim
from the issuer spelled out in a record.

NO SECRETS, EVER: tokens, keys, passwords, session cookies, signatures, or any
part of them. Not a prefix, not the last four characters, not "redacted" with the
value still in a neighbouring field. A credential that is expired, revoked or
simply wrong is still a credential and still must not be logged.

Two mechanisms put personal data into logs by accident, and both have already
happened on this network this week. Neither was anyone being careless; both are
the obvious code doing the obvious thing.

LOG THE SERVED PATH, NOT THE CLIENT-INFLUENCED ONE. A framework's "request URL"
is commonly reconstructed from the Host header, which the client controls, so
logging it records something the caller chose rather than what your router
matched. Log the routed path — in an ASGI application, `request.scope['path']` —
and record the Host as its own separate field if you want it. Measured and fixed
on two services on this network (orbit 20261008-038, 20261008-039); the test that
holds it forges a Host and asserts the logged path is unchanged.

AND NEVER THE QUERY STRING. This is the one that catches everyone, because
nobody thinks of a URL as personal data. `GET /persons/by-email?email=...`
carries an email, and `GET /api/members?q=...` carries whatever name was typed
into a search box — both real, both on this network, both from logging the full
URL rather than the path. Log the path and the route; drop the query entirely. If
one parameter genuinely must be kept, name it explicitly and allowlist it;
redacting a denylist of known-bad names fails the first time somebody adds a
parameter.

The general shape, and it is worth stating because it generalises past logging:
INSTRUMENTATION IS NOT EXEMPT FROM THE RULE IT MEASURES. Debug dumps, assertion
messages and error paths carry the payload, and the happy path staying clean is
what makes the red path's leak invisible.

A redactor that has never been shown a string it failed to catch is untested.
Feed it a known sentinel and assert the sentinel is absent from the output — the
two fixes cited above are both held by exactly that test, with the old behaviour
put back to prove the test fails.

### Retention: what a producer may assume

A producer may assume NOTHING about retention and must behave correctly if
records are kept for an hour or for a year. Specifically:

- LOGS ARE NOT A DATABASE. Anything the application needs later goes in the
  application's own storage. A record written only to the log is a record that
  may be gone.
- LOGS ARE NOT AN AUDIT TRAIL ON THEIR OWN. Where a regulation or a contract
  requires an auditable history — who changed what, who saw what — the
  application keeps that itself, in storage it controls, with its own retention.
  Security events go to the log as well, so a SOC can see across apps; the log
  is the second copy, never the only one.
- RETENTION IS THE CONSUMER'S DECLARATION, per environment, and a producer that
  needs a guarantee asks for it rather than assuming the default.

The one thing a producer DOES owe: volume it can defend. An endpoint logging one
record per request is fine; one logging a record per row returned is a producer
that takes the collector down on a slow day. Sample ordinary records if you must
— never security events, never errors — and say in the record that sampling is
on, because a consumer cannot distinguish a sampled stream from a quiet one.

### Declaring this out of scope

Not every project emits anything. A library, a template repository, a collection
of documents — none of them has logs, health endpoints or metrics.

Say so in `.devbox-git-profile`, as rendered destination paths:

    conventions_exempt=docs/OBSERVABILITY.md

`conventions` then reports that convention as `exempt` rather than `missing`, and
renders nothing into the project. Absence of the declaration means IN SCOPE —
exemption is a decision and a decision has to be written down.

### Where this comes from

Taken from existing standards rather than invented, so that a producer written
against the standard is already compliant:

- FIELD NAMES AND SEVERITY: OpenTelemetry semantic conventions and the
  OpenTelemetry logs data model, including the severity number scale.
- TRANSPORT: OTLP over HTTP, the OpenTelemetry Protocol specification.
- MACHINES THAT CANNOT SPEAK OTLP: RFC 5424 syslog, structured-data element.
- ERROR REPORTS: the Sentry protocol's envelope and event shape, for producers
  that have a client for it.
- METRICS EXPOSITION: the OpenMetrics text format.
- HEALTH ENDPOINT NAMING: the `/healthz` and `/readyz` convention as used by
  Kubernetes probes, chosen because it is what operators already expect.
- THE LOGIN AND ROLE VOCABULARY is consistent with this network's identity
  convention: `user.id` is the app's own local id for the `(iss, sub)` pair, not
  the subject claim itself.

The three leak rules — the served path, the query string, and the rejected
validation value — are not from a standard. They are from this network's own
measured findings, cited where they appear above.
<!-- devbox-conventions END -->

## Where wisenotes stands (outside the generated section)

Operator decision 2026-10-22 (ticket 20261020-042): JSON logs in this
vocabulary; keep `/health`; metrics and security events waived, as recorded
below.

**Logs: met.** `app/logs.py` writes every record, uvicorn's included, as one
JSON object per line on standard output, with the required fields under their
exact names. The values come from:

- `service.name`: `wisenotes`, or `OTEL_SERVICE_NAME` when set.
- `service.version`: `WISENOTES_VERSION`, which `deploy/deploy.sh` passes to
  the image build as the commit. It is `unknown` when the build was not told.
- `deployment.environment`: `WISENOTES_ENVIRONMENT`. The image sets `prod`,
  and a run from a checkout defaults to `dev`. A value off the scale logs as
  `dev`, with a warning.

There is one record per request (logger `wisenotes.request`). It carries the
routed path (`url.path`), the route template (`http.route`), the method, the
status and `duration_ms`. Severity follows the outcome: INFO below 400, WARN
for a 4xx, ERROR for a 5xx. The record never carries the query string or the
Host header. uvicorn's access log is off, because its line carries the query
string. `/health` is not logged. Every record logged while a request is
served carries that request's `correlation_id`. There is no trace, so there
is no `trace_id`.

An exception record carries `exception.type`, an `exception.message` taken
from the fixed reason table in `app/services/reasons.py`, the stack frames
without the final message line, and an `error.fingerprint` on the type and the
innermost frame. The exception's own text is left out: an `OSError` names a
path in the data directory, and a note's folder is named after its title.
For the same reason, no record names a note's title or folder, or an import
entry. `tests/test_logs.py` holds each of these rules with a sentinel.

What it does not do: there is no OTLP exporter, so
`OTEL_EXPORTER_OTLP_ENDPOINT` changes nothing. Records go to standard output,
where podman and the systemd user unit keep them (`podman logs`). The
document allows this: no endpoint configured is a valid mode. A routed path
can still contain an image's file name (`/notes/{note_id}/media/{filename}`),
which is what the rules above call the routed path.

**Health: `/health` kept, by decision.** `GET /health` answers `ok` with
no dependency check. That is the liveness answer under another name. There is
no `/readyz`, because the app has no dependency outside its own process to
wait for: notes are files in its data directory. `deploy/deploy.sh` (the smoke check)
and `deploy/preview.sh` (the deaf check) read `/health`, so a rename would be a
deploy change in all three places at once.

**Metrics and security events: waived** while wisenotes is single-user and
reached only over the tailnet (`deploy/README.md`, "Accepted risks"). There is
no login, so there is no authentication, authorisation or session event to
emit. One operator on one box does not need a `/metrics` series. The waiver
ends, and this section must be revisited, at the first of:

- a second user;
- a login of any kind;
- exposure beyond the tailnet.

`docs/IDENTITY.md` is out of scope for the same reason. The declaration
(`conventions_exempt=docs/IDENTITY.md` in `.devbox-git-profile`) is merge
request 20261022-043, ticket 20261022-037.

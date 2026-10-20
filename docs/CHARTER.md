# CHARTER.md — what wisenotes is, what it refuses, how requests are routed

This file is the basis on which a request is accepted or refused. A request it
does not cover goes to the operator; it is not accepted because the charter
did not forbid it.

Paths are on `develop`. A commit sha is cited where it carries the decision.

## Goals

1. **A fast, server-rendered note app.** Notes contain chapters, and chapters
   contain typed blocks: paragraph, code, math, media
   (`app/blocks.py`, 64a98f6). A graph block is planned, using self-hosted
   JSXGraph (operator, 2026-10-14).
2. **Every journey works without JavaScript; htmx only enhances.** The
   precedent is the no-JS audit, ticket 20260915-010. With scripts off, it
   found 10 of 15 journeys failing and 2 half-working. The fix is e9573f6.
   The audit's driver `tests/journeys.py` (0c184a3) runs every journey twice: once with scripts off, and once with them on as
   the control arm.
3. **File-based storage, one folder per note.** No database
   (`app/services/storage.py`).
4. **A small surface.** One enhancement script, `app/static/js/app.js`, with
   its drag-and-drop module `drag-drop.js` and an 8-line pre-paint
   `init-layout.js` (39e174e replaced `app.js` and nine modules). No build
   step, no SPA framework. Third-party code is vendored under
   `app/static/vendor/`.

## Non-goals

- Multi-user accounts, sharing or permissions. One operator, one data
  directory.
- Real-time collaboration, or sync across devices beyond the server itself.
- A JavaScript-only editing experience, such as a rich-text WYSIWYG editor
  with no form behind it.
- A database backend. If file storage stops being enough, the operator
  decides; this file does not.

## Refusal rules

Each rule names what is refused and the acceptable alternative. A refusal is
written on the request's ticket with the rule's number.

**R1. A feature that only works with JavaScript.** Refused, unless it has a
plain path:
- a `<form action method>` or an `<a href>` under every `hx-*` attribute;
- a full page for every route a fragment can reach;
- a 303 redirect for a POST without `HX-Request`.

The review checklist is `CONTRIBUTING.md`, "The no-JavaScript rule"
(f646cc5). Display-only enhancements may degrade to readable
source, as long as nothing is lost. Formulas and code already do this, and
the `<noscript>` notice says so (4db8fc2). A graph block falls
under that clause: without scripts it shows its definition text.

**R2. A new third-party runtime CDN.** Refused. Self-host the dependency in
`app/static/vendor/` (htmx precedent: 6e6acdd). There is one
recorded exception, and it is not a precedent for others: **KaTeX stays on
cdn.jsdelivr.net with SRI** (ticket 20260915-029, decision 2026-09-18,
e1bd1a4). That decision rests on a measurement:
`tests/journeys.py --block-cdn` aborted every non-server host, and both arms
still passed 14/14, with math blocks showing their source text. A second
exception needs the same proof (the app works with the CDN unreachable) and
an operator decision. JSXGraph is self-hosted by operator decision and is
not an exception.

**R3. Storing uploads verbatim, and SVG.** Refused. The server decides
uploads by content (Pillow open and verify) and re-encodes them. It refuses
SVG with a 400 that says why. It serves only stored raster types as images
(ticket 20260923-023, 2211308). Pillow opens only PNG, JPEG, WebP and GIF
(`ALLOWED_FORMATS`), and refuses an image over `MAX_PIXELS` (50 million),
read from the header before any decoding (a1f1b23, both in
`app/services/image_processing.py`). Importers follow the same rule: images
in an imported bundle are re-encoded (52a621d), and an import is
all-or-nothing, so a bundle that fails part-way leaves no partial notes
behind (e58304f). The alternative for vector art is to export it as PNG.

**R4. Shared infrastructure contracts.** Accepted as an adopter only where
wisenotes is a *genuine* deployment target for that contract. Otherwise
refused in writing, with the reason. **Genuine** means all three of these
hold:
1. the operator has named the deployment;
2. it holds data that must survive a redeploy;
3. wisenotes, not the contract's author, would exercise the contract in
   routine operation.

Today's only deployment is the devbox preview, tracking `develop`, data in
`/home/claude/wisenotes` (operator, 2026-09-23; `deploy/README.md`,
fd754fc). It meets all three. Ticket 20260928-042 (adopt
`.devbox/update.sh`) argued its case from an agrarius production host.
That host was dropped on 2026-09-23, five days before the request was
written. Its premise has to be restated against the preview before the
request is accepted, and the decision is the orchestrator's (`decision_by`
on the ticket).

**R5. Changes to another project.** Never made from here. File `tick req
<project>`, and keep working on something else meanwhile.

## Routing

- **Integration branch: `develop`.** Topic branches are cut from
  `origin/develop` and merged `--no-ff` by pull request, never squashed.
  **`main` is the deployment surface,** promoted from `develop` and tagged
  (`docs/BRANCHING.md`, 3adadd3). Note the gap between that file
  and the deployment as run: the preview follows `develop`, not `main`
  (fd754fc). Promotion to `main` therefore deploys nothing today.
- **Who lands.** The wisenotes sub-orchestrator reviews and lands to
  `develop`. A worker opens a merge-request ticket (`tick mr`) and does not
  merge its own work.
- **When a landing counts.** `develop` is the preview, so every push to it
  redeploys onto the live notes. A landing counts as landed only after the
  preview's smoke check passes on the live notes (operator, 2026-10-14, on
  ticket 20261014-139). The smoke check is step 3 of the deploy in
  `deploy/README.md`.
- **Pushes.** The wisenotes sub may push `develop` after each gated landing
  and its own secret scan (operator, 2026-10-19, ticket 20261019-007). The
  rule never covers `main`, a force-push, `release/*` branches or tags; each
  of those goes through the orchestrator to the operator.
  `docs/GIT_WORKFLOW.md` §3 (306728c) records `develop`'s branch
  protection as the operator's open decision.
  `main` is protected on GitHub: pull requests only, no force-push
  (operator, 2026-09-21).
- **Verification.** A UI-visible change is not "verified" until it has been
  checked in a real browser (operator, 2026-10-14). Tests and a
  `curl` of the page are evidence of the server's answer, not of what
  renders. A merge request that could not run a browser says so. Browser
  checks run with `tests/journeys.py`, which needs a Playwright whose
  version matches the installed chromium: on devbox that is Playwright
  1.61.0 for chromium-1228. A newer Playwright from pip wants a different
  chromium build, and the run fails at browser launch before testing
  anything.
- **Escalate to the operator:** anything that leaves the box, a second CDN
  exception (R2), a change of storage model, and a request this charter does
  not cover.

## Accepted risks

- **No CSRF protection.** Forms post without tokens, and nothing checks
  `Origin`. The operator accepts this while the app is reachable only over
  the tailnet (operator, 2026-10-14). **The acceptance ends on any exposure
  beyond the tailnet** (a public bind, `tailscale funnel`, a reverse proxy,
  a second user): CSRF protection is then a precondition of that change.
  The record is `deploy/README.md`, "Accepted risks".

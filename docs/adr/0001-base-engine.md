# ADR 0001 — Base engine

- Status: **proposed** (decided at GATE 0 by the project owner)
- Date: 2026-11-24
- Scope: which open-source office engine the Windows (and later Ubuntu) product is built on

## Decision proposed

Build on **upstream LibreOffice core, tag `libreoffice-26.8.3.1`**
(commit `861effc5289d539f15c4c18d1ba8579ffd78728b`), the source of the
26.8.3 stable release. Keep Collabora Office desktop as a watched
alternative, not as the base.

This confirms the default named in the brief.

## Evidence for the pin

All of this is re-checkable with `python3 -m tools.pin.verify_pin`
(result in `compliance/evidence/upstream-pin.json`, 7 of 7 checks passed).

| Check | Result |
|---|---|
| Newest directory under the official `stable/` listing on 2026-11-24 | `26.8.3/` (others: `25.8.7/`, `26.2.7/`, `26.8.2/`) |
| Source archive in the official `src/26.8.3/` directory | `libreoffice-26.8.3.1.tar.xz` — so release 26.8.3 is the `26.8.3.1` build |
| Tag on the official repository `https://gerrit.libreoffice.org/core` | `libreoffice-26.8.3.1` → `861effc5…` |
| Same tag on the read-only mirror `https://github.com/LibreOffice/core` | same commit |
| Official Linux x86-64 release archive | SHA-256 `e7cd3538…dcabf`, equal to the value served by `download.documentfoundation.org` |
| Build id inside that release (`program/versionrc`) | `861effc5…`, the pinned commit |

Not done: the OpenPGP signature of the release archive was downloaded but
not verified (the signing key was not fetched). How to verify: import the
release key published by The Document Foundation, then
`gpg --verify LibreOffice_26.8.3_Linux_x86-64_deb.tar.gz.asc`.

## Options considered

### A. Upstream LibreOffice core (proposed)

- Licence as stated in the tree: `readlicense_oo/license/license.xml:10`
  — "This product is made available subject to the terms of the Mozilla
  Public License, v. 2.0." The same file lists LGPL texts inside a
  `no_mpl_subset` block; `COPYING.MPL` is the MPL-2.0 text, `COPYING.LGPL`
  the LGPL-3.0 text, `COPYING` the GPL-3.0 text.
- Upstream maintains an MPL-only configuration: `configure.ac:1750`
  `--enable-mpl-subset` — "Don't compile any pieces which are not MPL or
  more liberally licensed"; with it configure sets `LICENSE="MPL-2.0"`
  (`configure.ac:16140`), otherwise `LICENSE="LGPL"` (`configure.ac:16083`).
- Windows build inputs are versioned inside the tree (`.config/2022.vsconfig`,
  `.config/*.winget`), see `docs/build-machine-requirements.md`.
- Rebranding switches exist in the build system (`--with-vendor`,
  `--with-product-name`, `--with-branding`, `--with-theme`), see
  `docs/branding-plan.md`.
- The base's own packaging produces an MSI (`--with-package-format`,
  used with `msi` in `distro-configs/LibreOfficeWin64.conf`).
- Baseline fidelity on our seed corpus with the unmodified official
  build: 84 of 114 documents pass, 30 partial, 0 fail
  (`reports/fidelity.json`, run `20261124T222749Z-7627aa7a`).
- Support window from the upstream release plan (wiki page
  `ReleasePlan/26.8`, revision 896825): the page's "End of Life" table
  gives **June 13, 2027**, under the caption "no more bugfix releases
  will be created from the 26-8 code branch by TDF". Bug-fix releases
  26.8.4, 26.8.5, 26.8.6 and 26.8.7 are listed; their dates are template
  parameters whose meaning was not expanded (UNKNOWN; read the rendered
  page). **Consequence:** the product must move to a newer upstream line
  before mid-2027, or carry security fixes itself after that date.

### B. Collabora Office desktop (not proposed)

What was read (pages saved on 2026-11-24, upstream tree at the pin):

- Collabora describes two desktop products. Quote: "We're excited to
  share the first release of the new Collabora Office for desktop –
  bringing the familiar, powerful Collabora Online experience, to run
  locally on Windows, macOS, and Linux." The other is "Collabora Office
  Classic — Powerful desktop editing, with classic UI".
- The upstream tree carries a configuration for the new desktop app:
  `distro-configs/CODAWindows.conf`, first line "# Collabora Online
  Desktop app for Windows". It builds the core headless
  (`--enable-headless`, `--disable-win`) without Java (`--without-java`),
  and contains an "# MPLv2 subset" block (`--with-theme=colibre`,
  `--disable-mariadb-sdbc`, `--disable-postgresql-sdbc`,
  `--disable-lotuswordpro`, `--disable-lpsolve`, `--disable-poppler`,
  `--disable-gpgmepp`).
- Licence notice of the desktop app's repository
  (`CollaboraOnline/online`, file `COPYING`): "This Source Code Form is
  subject to the terms of the Mozilla Public License, v. 2.0."
- Collabora trademark policy, point 7: "Distributing modified Collabora
  Productivity binaries: In making such a distribution you must remove
  all trademark uses of the Marks from the version of the Collabora
  Productivity software you are modifying." Point 4: "You should not
  include any of the Marks in the name of your application, product or
  service without our written permission".

Why it is not proposed as the base:

1. The new desktop app is the Collabora Online user interface running
   locally over a headless core. That is a second large code base (the
   online UI) on top of the core, with its own release line
   (tags `coda-25.04.x`). Requirements in our scope that depend on the
   classic desktop shell — presenter view, printing dialogs, the MSI
   produced by the base's own packaging — are UNKNOWN there and were not
   measured.
2. Third-party build documentation for an installable Windows package of
   that app was not found in the material read (UNKNOWN; verify in the
   `CollaboraOnline/online` repository).
3. Its release tags are named `coda-25.04.x` (for example
   `coda-25.04.9.2-2`). Which upstream core line and security-fix level
   that corresponds to is UNKNOWN; verify from the core branch the app's
   build instructions name.
4. Trademark work is the same either way: both policies require removing
   the upstream marks from a modified build.

What we take from it: `CODAWindows.conf` is an upstream-maintained
example of a reduced, Java-free Windows configuration and a useful
starting point for Phase 2. It is **not** an MPL-only build by itself:
it only switches off components (its "# MPLv2 subset" block), it does
not pass `--enable-mpl-subset`, and it passes `--with-fonts`, which
without the MPL-subset switch still packages the Culmus fonts
(`Repository.mk:1061`).

### C. ONLYOFFICE or proprietary SDKs

Excluded by the brief; not evaluated.

## Consequences

- Phase 1 builds the unmodified tag with upstream's Windows release
  switches (`distro-configs/LibreOfficeWin64.conf`).
- Phase 2 decides between the default (MPL + LGPL parts) and
  `--enable-mpl-subset`. The MPL-only build drops, per `configure.ac`:
  report builder, PostgreSQL and MariaDB drivers, Lotus Word Pro import,
  bundled Poppler (PDF import), lp_solve, gpgmepp, the GPL/LGPL icon
  themes, the Culmus fonts, and it clears `ENABLE_OPENGL_TRANSITIONS`
  (`configure.ac:16129`) — the last one touches slide transitions and
  must be measured against the parity matrix before it is chosen.
- Version scheme: `<upstream version>-<our patch level>`, starting at
  `26.8.3.1-0`. Each upstream 26.8.x release triggers a rebase of
  `patches/` and a full harness run.

## Open points for the owner

1. Approve option A and the pin, knowing the 26.8 line ends on
   June 13, 2027.
2. Say whether an MPL-only build (`--enable-mpl-subset`) is preferred if
   the transition measurements allow it. Whether that is the better
   compliance position is a legal judgement, flagged for human review.
3. Confirm that upstream test documents may be used as test input
   (ledger row `corpus-upstream-test-documents`).

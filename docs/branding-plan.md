# Branding and trademark plan (v0)

`PRODUCT_NAME` is not set yet. This plan uses the placeholder
`PRODUCTNAME`; the apps are "PRODUCTNAME Write" and "PRODUCTNAME Present".
Nothing below has been built: it is the plan for Phase 2.

## 1. Rules we must meet

1. No Microsoft names, icons, artwork, templates, sounds, proofing tools
   or fonts in the product. Factual compatibility statements are allowed
   ("opens .docx files").
2. No upstream name or logo on a modified build; credit upstream only in
   wording its policy allows.

## 2. The upstream policy, quoted

Source: The Document Foundation wiki, page "TDF/Policies/Trademark
Policy", revision 266041 dated 2020-05-14 (fetched 2026-11-24). The page
says: "The text in English is the official version of the Mark Policy and
shall be regarded as its default and binding version."

Marks covered:

> Marks cover the names "The Document Foundation" and "LibreOffice" as
> well as the paper clip icon.

When the name may be used for software:

> 1. To refer to the LibreOffice software in substantially unmodified form.
>
> "Substantially unmodified" means built from the source code provided by
> TDF, possibly with minor modifications including but not limited to: the
> enabling or disabling of certain features by default, translations into
> other languages, changes required for compatibility with a particular
> operating system distribution, the inclusion of bug-fix patches, or the
> bundling of additional fonts, templates, artwork and extensions).

Wording allowed for a modified build:

> 4. When referring to LibreOffice that is not substantially unmodified,
> to say that such software is a "derivative of" or "based on" LibreOffice.

Not allowed:

> In any way likely to cause confusion as to the identity of TDF, the
> origin of its software, or the software's license […]
>
> In any way that implies a designated successor to LibreOffice […]
>
> Thus uses of the marks in a domain name or company name without explicit
> written permission from TDF are prohibited.

### How we apply it

- Our build renames the product, hides modules and changes defaults, so
  we treat it as **not** "substantially unmodified" and remove the marks.
  (Whether a lighter build could keep the name is a legal judgement; we
  do not rely on it. Flagged for human review.)
- The only upstream credit in the product is one sentence in the About
  dialog and in THIRD-PARTY-NOTICES, using the policy's own wording:
  **"PRODUCTNAME is based on LibreOffice."** No upstream logo, no paper
  clip icon, no "LibreOffice" in product, executable, package, registry
  or domain names.
- Questions the policy does not answer go to the address the policy
  names (legal@documentfoundation.org); the owner decides whether to ask.

## 3. Build-system switches (exact names from the pinned tree)

| Purpose | Switch | Where it is defined |
|---|---|---|
| Product name | `--with-product-name='…'` — "Define the product name. Default is AC_PACKAGE_NAME." | `configure.ac:2208` |
| Vendor | `--with-vendor="…"` — "Set vendor of the build." | `configure.ac:3147` |
| Brand images | `--with-branding=/path/to/images` — "Use given path to retrieve branding images set." It searches for `intro.png`, `about.svg`, `logo.svg` and `progress.conf` | `configure.ac:3113` |
| Icon theme | `--with-theme="theme1 theme2..."` | `configure.ac:2448` |
| Release build | `--enable-release-build` | `configure.ac:2146` |
| Extra build id in About | `--with-extra-buildid="…"` — "Show addition build identification in about dialog." | `configure.ac:3141` |
| Privacy policy URL | `--with-privacy-policy-url="…"` — needed only "when enabling online-update or crashreporting via breakpad"; we enable neither | `configure.ac:3152` |
| Windows package | `--with-package-format` (upstream release config uses `msi`) | `configure.ac:2488` |

Not yet read in the tree (UNKNOWN, to be mapped at the start of Phase 2,
before any patch is written):

- where executable names, Start-menu names, `.ico` files and MSI text
  come from (candidates named by directory only: `sysui/`, `scp2/`,
  `instsetoo_native/`);
- which user-visible strings still say the upstream name after the
  switches above are set (About dialog, links, update and feedback URLs,
  document "generator" metadata, PDF producer string);
- whether the About dialog can gain a "Licences and source" entry by
  configuration or needs a small patch.

Each item found that the switches do not cover becomes one small patch in
`patches/`, with a test.

## 4. Assets we create

| Asset | Constraint |
|---|---|
| Product name and two app names | cleared by the owner against existing trademarks (not done; needs the name first) |
| App icons (Write, Present, document types) | original artwork; no resemblance to Microsoft or upstream icons |
| `intro.png`, `about.svg`, `logo.svg` | original; sizes taken from the upstream defaults they replace |
| Installer banner and dialog images | original |
| Document templates | original or CC0; none copied from Microsoft or upstream galleries |

The Colibre icon theme stays for toolbar icons: its licence file
(`icon-themes/colibre/COPYING-ICONS`) says "Icon theme is released under
Creative Commons CC0". Its `brand/` sub-directory holds upstream logos and
is replaced.

## 5. Checks that keep it true

Planned CI gate (Phase 2 onward), run on the unpacked installer payload:

- forbidden strings (case-insensitive, also inside UTF-16 resources):
  Microsoft marks named in the brief and the upstream marks quoted above,
  with an allow-list for the one credit sentence and for licence texts;
- forbidden assets: SHA-256 list of every upstream brand image at the
  pinned tag, and of any Microsoft font file name;
- the gate fails the build on a hit.

## 6. Open points for the owner

1. Choose `PRODUCT_NAME` and confirm it is clear to use.
2. Confirm the credit sentence.
3. Decide whether to write to the upstream foundation about the planned
   naming before the first public release.

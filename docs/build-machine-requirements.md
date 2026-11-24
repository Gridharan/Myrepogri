# Build-machine requirements (Windows) — quoted from upstream at the pin

Everything here is quoted from files inside the pinned tree
(`libreoffice-26.8.3.1`, commit `861effc5…`) unless marked otherwise.
Nothing has been installed or built yet: this is the input for
`build/win/bootstrap.ps1` in Phase 1.

> **Status of the build machine.** Phase 0 ran in a Linux cloud container.
> No Windows machine was available to the session, so nothing in this
> file has been executed. Phase 1 cannot start until a Windows 10/11 x64
> machine is reachable (see section 7).

## 1. Baselines — `README.md`, "The Build Chain and Runtime Baselines"

> * Windows:
>     * Runtime: Windows 10
>     * Build: [wsl-as-helper](…/Development/BuildingOnWSLWindows) + Visual Studio 2022

> The baseline for Java is Java Development Kit (JDK) Version 17 or later.

> The baseline for Python is version 3.11.

> You can find the TDF configure switches in the `distro-configs/` directory.

## 2. Visual Studio — `.config/2022.vsconfig` (whole component list)

```
Microsoft.VisualStudio.Workload.CoreEditor
Microsoft.VisualStudio.Workload.NativeDesktop
Microsoft.Net.Component.4.8.SDK
Microsoft.VisualStudio.Component.VC.ATL
Microsoft.VisualStudio.Component.VC.CMake.Project
Microsoft.VisualStudio.Component.VC.Llvm.Clang
Microsoft.VisualStudio.Component.VC.Redist.MSM
Microsoft.VisualStudio.Component.VC.Tools.x86.x64
Microsoft.VisualStudio.Component.Windows11SDK.22621
```

`.config/configuration.winget` installs it as
`Microsoft.VisualStudio.2022.Community` ("Install Visual Studio 2022
Community"). **Licence check needed:** which Visual Studio edition our
organisation may use for a commercial product is the owner's decision
(ledger row `planned-visual-studio`).

`configure.ac:3011` — `--with-visual-studio=<2022>`: "Specify which Visual
Studio version to use in case several are installed. Currently 2022
(default) is supported."

## 3. Tools — `.config/admin_java_and_deps.winget` (URL and SHA-256 as pinned by upstream)

| Tool | Source named by upstream | SHA-256 named by upstream |
|---|---|---|
| jom 1.1.4 | `http://download.qt.io/official_releases/jom/jom_1_1_4.zip` | `d533c1ef…562682b` |
| GNU make 4.2.1 (Windows build) | `https://dev-www.libreoffice.org/bin/cygwin/make-4.2.1-msvc.exe` | `146d6f2b…2423d8` |
| clang-format 5.0.0 | `https://dev-www.libreoffice.org/bin/clang-format-5.0.0-win.exe` | `a25d5c4b…a73ccb` |
| pkgconf 2.4.3 | `https://dev-www.libreoffice.org/extern/pkgconf-2.4.3.exe` | `791cd6db…52edd41` |
| Strawberry Perl 5.40.0.1 portable | `https://github.com/StrawberryPerl/Perl-Dist-Strawberry/releases/download/SP_54001_64bit_UCRT/strawberry-perl-5.40.0.1-64bit-portable.zip` | `754f3e2a…933907` |
| Apache Ant 1.10.17 | `https://dlcdn.apache.org/ant/binaries/apache-ant-1.10.17-bin.zip` | `70608b74…567567` |
| JUnit 4.10 | `https://repo1.maven.org/maven2/junit/junit/4.10/junit-4.10.jar` | `36a747ca…b0f75a` |
| JDK 17.0.12+7 x64 (Temurin) | `https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.12%2B7/OpenJDK17U-jdk_x64_windows_hotspot_17.0.12_7.msi` | `1e6df6b4…889835` |
| JDK 17.0.12+7 x86 (Temurin) | `…/OpenJDK17U-jdk_x86-32_windows_hotspot_17.0.12_7.msi` | `84e94caa…0b4f11` |

The full 64-character digests are in the upstream file; `bootstrap.ps1`
must read them from the pinned tree, not from this table. One source is
plain `http://` (jom): the checksum is what makes that download safe.

The same file makes sure WSL is installed: `wsl.exe --install
--no-distribution`, and installs the Media Feature Pack "when necessary
(for Windows N)".

## 4. WSL helper — `.config/user_steps.winget`

- Distribution: `wsl.exe --install --no-launch --distribution Ubuntu-24.04`
- Packages inside it: `packages: [pkg-config, automake, make, gperf, bison, nasm, flex, zip, gettext]`
- Git settings: `git config --global core.autocrlf false` and
  `git config --global protocol.version 2`
- Reboot: the file checks the "Component Based Servicing\RebootPending"
  registry key after installing WSL — a reboot can be required mid-setup,
  so `bootstrap.ps1` must be resumable across a reboot.

## 5. Configure input

Developer defaults written by `.config/user_steps.winget`:

```
--host=x86_64-pc-cygwin
--disable-ccache
--with-visual-studio=2022
--enable-python=fully-internal
--without-lxml
--disable-online-update
--with-external-tar=$env:USERPROFILE\lo\lo-externaltar
--with-strawberry-perl-portable=$env:USERPROFILE\lo\spp
--with-ant-home=$env:USERPROFILE\lo\apache-ant-1.10.17
--with-junit=$env:USERPROFILE\lo\junit-4.10.jar
--with-doxygen=$env:USERPROFILE\lo\spp\c\bin\doxygen.exe
```

Upstream's Windows x64 release switches — `distro-configs/LibreOfficeWin64.conf`
(complete file):

```
--host=x86_64-pc-cygwin
--without-junit
--without-helppack-integration
--enable-extension-integration
--enable-scripting-beanshell
--enable-scripting-javascript
--enable-ext-wiki-publisher
--enable-ext-nlpsolver
--enable-online-update
--enable-online-update-mar
--enable-breakpad
--with-help=html
--with-myspell-dicts
--with-package-format=msi
--enable-mergelibs=more
--enable-lto
--enable-odk
```

`distro-configs/README.md` says these files are passed as
`./autogen.sh --with-distro=LibreOfficeFoo`.

Phase 1 builds "exactly per upstream docs", so it uses the release file
above. Note for Phase 2: that file turns **on** online update
(`--enable-online-update`, `--enable-online-update-mar`) and crash
reporting (`--enable-breakpad`); our product configuration turns them off.

## 6. Unversioned upstream page (context only)

Wiki page "Development/BuildingOnWindows", revision 888319 dated
2026-08-06. It is not tied to the tag; where it disagrees with the tree,
the tree wins. Lines used:

- "These instructions assume you have not installed any WSL container."
- `winget configure -f lo/libo-core/.config/configuration.winget`
- `winget configure -f lo/libo-core/.config/admin_java_and_deps.winget`
  (run as administrator)
- `winget configure -f lo/libo-core/.config/user_steps.winget` (normal user)
- "If wsl wasn't install previously, you must reboot to complete the
  installation!"
- `wsl ./autogen.sh`
- The page has sections on antivirus products interfering with the build
  and on a failing first `winget` run on a fresh Windows installation.

Wiki page "Development/lode" (LibreOffice Development Environment),
revision 886630 dated 2026-07-16, also unversioned:

- "count 25 GB to be safe with one debug build environment... for a
  Jenkins slave at least 100 GB should be provisioned."
- "This may take 1 to 2 hours, or more depending on your machine."

## 7. Not stated by upstream in what was read (UNKNOWN)

| Item | How to find out |
|---|---|
| RAM, and disk space and build time for a *release* build (the LODE page quoted in section 6 gives only a debug-build disk figure and a rough time) | measure in Phase 1 and record in `build/BUILDINFO.json`; plan for well above 25 GB |
| Whether the Windows target can be cross-built from Linux | search `configure.ac` for the host/build checks; until shown otherwise assume **no**, because the documented chain is Visual Studio on Windows |
| Which Windows SDK tools the MSI packaging calls, and how the Visual C++ runtime is shipped (the component list includes `VC.Redist.MSM`) | read `solenv/bin/modules/installer/windows/` and `scp2/` at the start of Phase 1 |
| Test targets and their Windows behaviour | read `Makefile.in` and `solenv/gbuild` help text at the start of Phase 1 |

## 8. What Phase 1 needs from the owner

1. A Windows 10 or 11 x64 machine the session can reach. Options: run the
   session on that machine, or attach it with Remote Control
   (`claude remote-control` in the project folder). A Linux VPS cannot
   stand in for it.
2. Administrator rights on it for the two admin-level setup steps, and
   permission to reboot once.
3. The Visual Studio edition and licence to use.
4. Outbound access from that machine to the hosts in section 3 during
   bootstrap (the product itself needs no network).

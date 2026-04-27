# Code signing with SignPath Foundation (free for open source)

This guide walks through signing Söyle releases with a real
Authenticode certificate **at zero cost**, using the
[SignPath Foundation](https://signpath.org/) free signing program for
open-source projects.

Result after the steps below:

- Installer shows `Verified publisher: SignPath Foundation` in the UAC
  dialog instead of `Unknown publisher`.
- Most antivirus engines stop flagging the `.exe` as suspicious.
- Windows SmartScreen reputation builds much faster; after a few dozen
  downloads users stop seeing the "Windows protected your PC" screen.
- Corporate AppLocker / WDAC policies that require any signature let
  the installer through.

Total out-of-pocket cost: **$0** (forever, as long as the project stays
open-source).

---

## Step 1 — Apply to the SignPath Foundation

1. Open <https://signpath.org/apply>.
2. Select **"Open Source Project"** and fill in:
   - **Project name:** `Söyle`
   - **Repository URL:** `https://github.com/nurgisa/soyle`
   - **License:** MIT (they require an OSI-approved license — MIT
     qualifies).
   - **Description:** a couple of sentences about what the app does.
   - **Maintainer contact:** your real name and email.
3. Submit. Expect **1–2 weeks** for manual review. They check that:
   - The project is genuinely open source (public repo, OSI license).
   - The maintainer is a real person (they may email-verify).
   - The project has some activity (commits, a README, issues —
     anything showing it's not a throwaway).

If approved, they send an invite email to create an account at
<https://app.signpath.io/>. From there you define a **Signing Policy**
that tells SignPath *which workflow from which repo is allowed to
request signatures for which artifacts*.

## Step 2 — Create the SignPath project and policy

After logging into SignPath:

1. **Organization → Projects → Add Project**
   - Name: `Söyle`
   - Slug: `soyle` (keep lowercase, used in the Action input).

2. **Project → Artifact Configurations → Add**
   - Type: `Windows Installer (.exe)`
   - Nested files: enable signing of the inner `Soyle.exe` too
     (SignPath unwraps the Inno Setup installer, signs the exe inside,
     re-signs the outer installer). This is important so both the
     installer and the installed app are signed.

3. **Project → Signing Policies → Add**
   - Slug: `release-signing`
   - Certificate: `Foundation OSS Authenticode` (the free one).
   - Trigger: GitHub Actions workflow
     - Repository: `nurgisa/soyle`
     - Workflow file: `.github/workflows/release.yml`
     - Branch / tag pattern: `refs/tags/v*`
   - Approvers: yourself (for OSS Foundation projects typically no
     human approval needed per release).

4. **Personal → API Tokens → Generate**
   - Name: `github-actions-release`
   - Scope: limited to the `Söyle` project.
   - Copy the token — you'll paste it into GitHub in a moment.

Also note the **Organization ID** (visible at the top of every
SignPath page, a UUID).

## Step 3 — Add GitHub repo secrets

In the GitHub repo: **Settings → Secrets and variables → Actions → New
repository secret**. Create four secrets:

| Secret name                     | Value                                          |
| ------------------------------- | ---------------------------------------------- |
| `SIGNPATH_API_TOKEN`            | The API token from Step 2.                     |
| `SIGNPATH_ORG_ID`               | Your Organization ID UUID.                     |
| `SIGNPATH_PROJECT_SLUG`         | `soyle` (or whatever slug you chose).    |
| `SIGNPATH_SIGNING_POLICY_SLUG`  | `release-signing`.                             |

Optionally also create a repository **variable** (not secret)
`SIGNING_ENABLED=true` so the workflow knows to submit signing
requests. Alternatively, hard-code the switch in the workflow file.

## Step 4 — Extend the release workflow

Replace the contents of [`.github/workflows/release.yml`](../.github/workflows/release.yml)
with the version below. It:

1. Builds the installer as before.
2. Uploads the unsigned installer as a build artifact.
3. Submits the artifact to SignPath for signing.
4. Downloads the signed result.
5. Attaches the signed `.exe` to the GitHub Release.

```yaml
name: release

on:
  push:
    tags: ["v*"]
  workflow_dispatch:

permissions:
  contents: write
  id-token: write   # required by SignPath OIDC workflow identity check

jobs:
  build-installer:
    runs-on: windows-latest
    timeout-minutes: 30
    outputs:
      artifact-id: ${{ steps.upload-unsigned.outputs.artifact-id }}

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        run: irm https://astral.sh/uv/install.ps1 | iex
        shell: pwsh

      - name: Install Inno Setup 6
        run: choco install innosetup --yes --no-progress
        shell: pwsh

      - name: Sync build deps
        run: uv sync --extra build
        shell: pwsh

      - name: Verify version matches tag
        shell: pwsh
        run: |
          $tag = "${{ github.ref_name }}" -replace '^v', ''
          $pyproject = uv run python -c "import tomllib, pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])"
          if ($tag -ne $pyproject.Trim()) {
            Write-Error "Tag $tag does not match pyproject.toml version $pyproject"
            exit 1
          }

      - name: Build installer
        run: uv run python scripts/build_installer.py
        shell: pwsh

      - name: Upload unsigned installer as build artifact
        id: upload-unsigned
        uses: actions/upload-artifact@v4
        with:
          name: installer-unsigned
          path: release/Soyle-Setup-*.exe
          if-no-files-found: error
          retention-days: 14

  sign-and-publish:
    needs: build-installer
    runs-on: windows-latest
    timeout-minutes: 30
    permissions:
      contents: write
      id-token: write
      actions: read

    steps:
      - name: Submit to SignPath for Authenticode signing
        id: signpath
        uses: signpath/github-action-submit-signing-request@v1
        with:
          api-token:              ${{ secrets.SIGNPATH_API_TOKEN }}
          organization-id:        ${{ secrets.SIGNPATH_ORG_ID }}
          project-slug:           ${{ secrets.SIGNPATH_PROJECT_SLUG }}
          signing-policy-slug:    ${{ secrets.SIGNPATH_SIGNING_POLICY_SLUG }}
          github-artifact-id:     ${{ needs.build-installer.outputs.artifact-id }}
          wait-for-completion:    true
          output-artifact-directory: release-signed

      - name: Attach signed installer to the GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: release-signed/Soyle-Setup-*.exe
          fail_on_unmatched_files: true
          generate_release_notes: true
          draft: false
```

Commit this change. The next `git push origin vX.Y.Z` will produce a
**signed** installer on the Releases page.

### Verify the signature

After the CI run finishes, download the `.exe` and right-click →
**Properties → Digital Signatures**. You should see:

- Signer: `SignPath Foundation`
- Digest algorithm: `sha256`
- Timestamp: present (important — without a timestamp the signature
  expires when the cert does).

Or from PowerShell:

```powershell
Get-AuthenticodeSignature .\Soyle-Setup-1.0.1.exe
```

Expected: `Status: Valid`.

## Step 5 — SmartScreen reputation

The first few downloads of a freshly signed `.exe` still trigger a
SmartScreen warning — Microsoft's system needs to observe the binary
being downloaded and run without crashes to build trust. With a signed
binary this takes **10-50 downloads** typically; unsigned binaries
effectively never earn reputation.

To speed it up:

- Share the download link in a public channel so multiple users
  download the same file.
- Report false positives at
  <https://www.microsoft.com/en-us/wdsi/filesubmission>.
- Don't rebuild unnecessarily — each new hash restarts reputation from
  zero. Use the same signed `.exe` for as long as it's current.

## Alternatives considered (paid but sometimes worth it)

- **Azure Trusted Signing** — $9.99/month via Microsoft, EV-equivalent,
  cert key in Azure HSM. Cheapest paid option.
- **DigiCert / Sectigo EV** — $400+/year, instant SmartScreen trust,
  requires a physical USB HSM token (not compatible with CI signing).
- **Standard Authenticode** — $200/year, same reputation-building
  curve as SignPath, so not worth paying for if you qualify for
  SignPath.
- **Microsoft Store** — $19 one-time developer fee, distribute as
  MSIX. Changes the download flow entirely (users install from Store,
  not GitHub) but the package is pre-trusted.

Stick with SignPath until one of these clearly becomes necessary.

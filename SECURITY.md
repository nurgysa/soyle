# Security policy

## Supported versions

Söyle is in early development. Only the **latest released version** on
the [Releases page](https://github.com/nurgysa/soyle/releases/latest)
receives security fixes. Older versions are not supported — please
upgrade if you're running anything older.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security problems.**

If you've found a vulnerability — anything that could expose user data,
allow code execution, leak the OpenRouter API key, or compromise the
local Whisper pipeline — report it privately:

- **Email:** `andasbek.nurgysa@gmail.com`
- **Subject line prefix:** `[SECURITY] Söyle: <short description>`

In your report, please include:

1. A clear description of the issue.
2. Reproduction steps (commit hash, OS version, relevant config).
3. The impact you've assessed.
4. (Optional) A suggested fix.

I aim to acknowledge reports within **72 hours** and ship a fix or
mitigation within **14 days** for critical issues. You'll be credited
in the [CHANGELOG](CHANGELOG.md) unless you prefer to stay anonymous.

If for any reason email is impractical, you can also use GitHub's
[Private Vulnerability Reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository.

## Out of scope

- Vulnerabilities in upstream dependencies (PySide6, faster-whisper,
  ctranslate2, OpenRouter, etc.) should be reported to those projects
  directly. If a dependency CVE affects Söyle materially, I'll publish
  a security advisory and bump the lockfile.
- Theoretical issues that require physical access to the user's
  unlocked Windows session.
- Social-engineering attacks against users (e.g. tricking them into
  pasting a fake API key).

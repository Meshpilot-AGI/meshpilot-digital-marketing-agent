# Security Policy

## Supported Versions

Security fixes are provided for the latest code on the `production` branch.

| Version | Supported |
| ------- | --------- |
| `production` branch | ✅ |
| Older branches, tags, and forks | ❌ |

## Reporting a Vulnerability

Please **do not report security vulnerabilities through public GitHub issues, discussions, pull requests, or social media**.

Instead, use GitHub’s private vulnerability reporting feature:

1. Go to the repository’s **Security** tab.
2. Select **Report a vulnerability**.
3. Provide a clear description, reproduction steps, affected components, impact, and any suggested remediation.

If private reporting is unavailable, contact the maintainers through the repository owner’s GitHub profile and clearly label the message **Security Vulnerability**.

## What to Include

Please include, where possible:

- A description of the vulnerability and its potential impact
- Steps to reproduce the issue or a proof of concept
- The affected branch, commit, deployment configuration, or dependency version
- Whether authentication, API keys, OAuth credentials, cloud permissions, or user data could be exposed
- Suggested mitigations or patches, if available

Please do not include real secrets, API keys, access tokens, customer data, or other sensitive data in the report.

## Response Process

We aim to acknowledge valid reports within **7 days** and will provide updates as the investigation progresses.

If the report is accepted, we will work to validate the issue, develop and test a fix, and release it as soon as reasonably possible. We may request further details during investigation.

After a fix is available, we may publish a security advisory and credit the reporter unless they prefer to remain anonymous.

## Scope

Examples of security-relevant issues include:

- Exposed or improperly handled API keys, tokens, or credentials
- Authentication or authorization bypasses
- Cross-tenant or cross-brand data access
- Prompt injection leading to unauthorized tool use or data disclosure
- Server-side request forgery, command injection, or remote code execution
- Unsafe handling of webhooks, OAuth callbacks, uploads, or third-party integrations
- Vulnerabilities affecting stored customer, campaign, analytics, or advertising-platform data

## Security Practices for Deployers

If you self-host Meshpilot, you are responsible for securing your deployment:

- Store secrets in environment variables or a managed secret store; never commit them to Git.
- Use least-privilege credentials for cloud, social, advertising, analytics, and AI-provider integrations.
- Restrict network access to administrative and internal service endpoints.
- Enable HTTPS, rotate credentials regularly, and keep dependencies updated.
- Review agent tool permissions and require human approval for high-impact actions where appropriate.

Thank you for helping keep Meshpilot and its users secure.

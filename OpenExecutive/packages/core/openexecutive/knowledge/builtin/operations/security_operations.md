# Security Operations

Security is the discipline that gets ignored until it can't be. Then it's both expensive and embarrassing. The companies that handle security well treat it as a baseline operating discipline — not a project, not a compliance checkbox, and not "the security team's problem."

## The Security Operating Model

Three layers, each with different work:

**1. Governance — what we commit to**
- Policies and standards (data classification, access, acceptable use, incident response)
- Compliance frameworks we adhere to (SOC 2, ISO 27001, HIPAA, GDPR)
- Risk register and acceptance decisions
- Board reporting and oversight

**2. Engineering — what we build to enforce**
- Identity and access management (SSO, MFA, RBAC)
- Endpoint security (MDM, EDR)
- Network and infrastructure security
- Application security (secure SDLC, code review, dependency management)
- Data security (encryption, DLP, key management)
- Logging, monitoring, detection

**3. Operations — what we do daily**
- Vulnerability management
- Patch management
- Access reviews
- Security awareness training
- Incident response
- Vendor security reviews

Companies often build engineering controls without governance (policies that don't reflect actual practice) or without operations (controls that decay because no one maintains them). Both fail audits and protect nothing in practice.

## The Security Maturity Stages

**Pre-formal (typical for <50 employees):**
- MFA on everything, SSO where possible
- Encrypted laptops with screen locks
- Some basic policies (acceptable use, password)
- A founder or CTO acting as security lead
- Customer security questionnaires answered case-by-case

**Foundational (50-200 employees):**
- Designated security owner (often head of IT, sometimes CISO)
- SOC 2 Type I working toward Type II
- Formal incident response process
- Security awareness training
- Vendor security review process

**Established (200-1000 employees):**
- Dedicated security team (3-10 people)
- SOC 2 Type II + often ISO 27001
- Centralized logging (SIEM)
- Vulnerability management program
- Annual penetration tests
- Security champion network across engineering

**Mature (1000+ employees):**
- CISO reporting to CEO or CTO
- Cross-functional security organization (governance, engineering, ops, threat intel, GRC)
- Multiple framework certifications
- Bug bounty program
- Red team exercises
- Industry-specific controls (FedRAMP, HITRUST, PCI)

The stages aren't bureaucratic — each represents capability needed at that scale.

## Identity and Access Management (IAM)

The single most leverage area in security. Most breaches involve compromised credentials.

**Baseline controls:**
- *MFA on everything* — non-negotiable, especially admin and production access
- *SSO for SaaS* — reduces credential sprawl; faster onboarding/offboarding
- *Role-based access control (RBAC)* — access based on role, not individual
- *Principle of least privilege* — minimum access needed to do the job
- *Just-in-time access* — elevated permissions granted temporarily for specific tasks

**Operational discipline:**
- *Onboarding checklist*: provisioning happens via standard process, not ad-hoc requests
- *Offboarding checklist*: access revoked within hours of separation; logs reviewed
- *Quarterly access reviews*: managers confirm each report still needs current access
- *Privileged access management*: admin accounts separately managed, often in dedicated tool (CyberArk, Okta PAM)

**The recurring failure mode:**
- Employee changes role; old access retained
- Cumulative "access creep" over years
- Eventually: a single compromised account has access to half the company's systems
- *Cure*: access reviews actually executed, not just scheduled

## Endpoint Security

Laptops and phones used by employees.

**Standard controls:**
- *MDM (Mobile Device Management)* — centralized control of company devices (Jamf, Kandji for Mac; Intune for Windows; Workspace ONE for mixed)
- *EDR (Endpoint Detection and Response)* — runtime threat detection (CrowdStrike, SentinelOne, Microsoft Defender)
- *Disk encryption* — FileVault, BitLocker enabled by default
- *Patch management* — OS and application updates pushed automatically
- *Acceptable use enforcement* — restricted software install, web filtering for some categories

**BYOD (Bring Your Own Device) considerations:**
- Personal devices increase attack surface
- MDM on personal devices is invasive and often refused
- Alternative: limit data access on unmanaged devices via app-level controls
- Most enterprise companies trend toward company-issued devices for production access

## Application Security

For companies building software (most tech companies).

**Secure Software Development Lifecycle (SDLC):**
- Security review at design phase (threat modeling)
- Static Application Security Testing (SAST) in CI
- Dependency / Software Composition Analysis (SCA) — track vulnerable libraries
- Dynamic Application Security Testing (DAST) for running applications
- Code review with security awareness
- Penetration testing (typically annual, after major releases)

**The OWASP Top 10:**
- Reference list of most-common web application vulnerabilities
- Updated periodically; current themes: injection, broken access control, cryptographic failures, design failures
- Most application security work prevents these

**Secrets management:**
- Never store secrets in code or config files
- Use dedicated secrets manager (AWS Secrets Manager, HashiCorp Vault, Doppler)
- Rotate secrets regularly; automated rotation for critical credentials

**API security:**
- Authentication on all endpoints
- Rate limiting and anomaly detection
- Input validation (don't trust client input)
- Logging for forensics

## Vulnerability Management

The continuous discipline of finding, prioritizing, and remediating vulnerabilities.

**Detection sources:**
- Vulnerability scanners (Nessus, Qualys, Tenable for infrastructure; Snyk, GitHub Advanced Security for code)
- Penetration tests
- Bug bounty programs
- Threat intelligence feeds (alerts on new CVEs affecting your stack)

**Prioritization:**
- Severity (CVSS score) modified by exposure (public-facing? authenticated? exploitable?)
- Patch availability and timeline
- Business impact if exploited
- Active exploitation in the wild (CISA KEV catalog)

**SLA for remediation:**
- Critical / actively exploited: 24-48 hours
- High: 7 days
- Medium: 30 days
- Low: best-effort

**The gap most companies have:**
- Detection works
- Prioritization works
- Remediation lags — patches aren't applied because eng teams are busy with features
- *Cure*: vulnerability remediation goes on engineering teams' commitments; tracked weekly; SLA breaches escalated

## Security Monitoring and Detection

**Centralized logging:**
- All security-relevant events flow to a central log system
- Retention: typically 90 days minimum, 1+ years for compliance
- Sources: cloud (AWS CloudTrail, GCP Audit Logs), identity (Okta, Azure AD), endpoints (EDR), applications (custom app logs), network (VPC flow logs)

**SIEM (Security Information and Event Management):**
- Tools: Splunk, Datadog, Sumo Logic, Elastic, open-source options
- Correlate events across sources
- Alert on suspicious patterns
- Investigation workbench for analysts

**Detection engineering:**
- Building specific detections for threats relevant to your environment
- Tuning to reduce false positives
- Continuous improvement based on incidents and threat intel

**The trap:**
- Most companies generate logs without actually monitoring them
- "We have it in Splunk" ≠ "we'd detect it"
- *Cure*: defined detection rules, alert routing, and on-call rotation

## Incident Response

When (not if) something happens. Detailed in `business_continuity.md`. Security-specific additions:

**Severity definitions:**
- *Sev 1*: confirmed breach, active attack, customer-data exposure
- *Sev 2*: suspicious activity, potential compromise, security control failure
- *Sev 3*: anomaly worth investigating, no evidence of compromise
- *Sev 4*: informational, policy violation

**Response team:**
- Incident commander (often security lead)
- Technical lead (investigates and remediates)
- Communications lead (internal + customer + regulator)
- Legal (regulatory obligations, evidence preservation)
- Executive sponsor (decision authority)

**Forensic discipline:**
- Preserve evidence before remediating (snapshots, logs)
- Document timeline meticulously
- External forensic firm for serious incidents (Mandiant, CrowdStrike, Stroz Friedberg)
- Postmortem within 5 business days

**Notification obligations:**
- Customer contracts often require breach notification (24-72 hours common)
- Regulators: GDPR 72 hours, US state laws vary
- See `data_privacy_and_security.md` for detail

## Security Awareness

Humans are the most-targeted vulnerability.

**Annual training:**
- Phishing recognition
- Password and credential hygiene
- Data handling and classification
- Incident reporting
- Required for compliance (SOC 2, etc.)

**Phishing simulations:**
- Simulated phishing emails sent to employees periodically
- Click-rate tracked and trended
- Failures route to additional training (not punitive)
- Tools: KnowBe4, Proofpoint, internal scripts

**Security champions:**
- Volunteer engineers/employees who advocate for security in their teams
- Get extra training and access to security team
- Multiply the security team's reach across the org

## Compliance vs. Security

A critical distinction.

**Compliance** — passing audits, having documentation, meeting framework requirements (SOC 2, ISO, HIPAA)

**Security** — actually being hard to compromise

These overlap but aren't the same. Companies can be SOC 2 compliant and easily breachable (controls exist on paper, not in practice). Companies can be highly secure and not have any certifications (early-stage with strong engineering culture).

**The honest leadership question:** are we focused on the certifications because they unlock deals, or because they reflect actual security improvement? Both can be true; the order of operations matters.

## Third-Party Risk Management

Your security is bounded by your vendors' security.

**Vendor security review:**
- For any vendor with access to data or systems
- SOC 2 report (or equivalent) reviewed
- Security questionnaire completed
- DPA in place if processing personal data
- Subprocessor list reviewed
- Annual refresh

**Common gaps:**
- Marketing tools collecting customer data with weak security
- Free or low-cost SaaS used by individual teams without review
- M&A inheriting weaker security posture
- Open-source dependencies with no maintenance

**Right-sizing the review:**
- Tier vendors by data sensitivity and access
- High-risk vendors: full review, annual refresh
- Low-risk vendors: lightweight review, longer refresh cycle
- Use vendor security platforms (OneTrust, Whistic, SecurityScorecard) at scale

## Common Security Failures

1. **MFA exemptions for executives** — "they're busy"; executives are also the most-targeted
2. **Shadow IT** — departments adopting tools without security review; eventual breach traces back
3. **Stale access** — former employees still in systems; contractors with full access years later
4. **Detection without response** — alerts fire, no one looks; effectively no monitoring
5. **Tabletop exercises skipped** — incident response plan never tested; real incident reveals gaps
6. **Vendor security as a checkbox** — SOC 2 collected but never reviewed
7. **Patching deferred** — vulnerability scanners flag, engineering says "later", eventually exploited

## The Security Diagnostic

For your security posture, answer:
1. Is MFA enforced on every production system? Every admin account? No exceptions?
2. When was our last access review? What did it find?
3. What's our patching SLA, and what's the compliance rate?
4. When did we last tabletop an incident? What did we learn?
5. What's the top security risk we know about and haven't addressed?

If you can't answer #5, you don't have a risk register. Build one — the unknown risk is always more expensive than the known one.

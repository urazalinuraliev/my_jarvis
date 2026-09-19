# AI and Data Law

The legal landscape for AI is moving faster than any other area of commercial law. Executives building with or deploying AI need to understand a patchwork of existing law (privacy, IP, employment, consumer protection) that applies to AI today, plus emerging AI-specific regulation that is being enacted across jurisdictions. Uncertainty is inherent — but inaction is not a risk-free posture.

## The Core Legal Risks of AI

**1. Intellectual property liability** — using training data you don't have rights to, or deploying model outputs that infringe third-party IP

**2. Privacy violations** — processing personal data in AI systems in ways that exceed the scope of consent or applicable law

**3. Discrimination and bias** — automated decision-making that produces disparate impact on protected classes

**4. Misinformation and hallucination liability** — deploying AI output without adequate human review in contexts where accuracy is legally required (medical advice, legal advice, financial advice, product safety)

**5. Regulatory non-compliance** — EU AI Act, emerging US state AI laws, sector-specific guidance from FTC, CFPB, EEOC, FDA

**6. Contractual liability** — breach of customer contracts through AI-introduced errors, latency, or data mishandling

## Intellectual Property

### Training Data Rights

The foundational legal question for AI companies: was the training data lawfully obtained?

**Copyright:** Works are copyrightable if original and fixed. Models trained on copyrighted works without a license may infringe — whether training itself constitutes infringement is actively litigated (Getty Images v. Stability AI, NYT v. OpenAI, others). Current best practice:
- If you're training your own model: use licensed datasets (Common Crawl, licensed corpora), public domain content, synthetic data, or data you own
- If you're using a third-party model via API: the API provider bears the training data risk; review their terms and indemnification provisions

**Fair use defense (US):** Possible but uncertain. Transformative use is the strongest argument; courts have not yet ruled definitively on whether LLM training is transformative.

**EU and other jurisdictions:** The EU's TDM (text and data mining) exception under the DSM Directive allows training on lawfully accessed content, with opt-out rights for rights holders. More structured than the US fair use approach.

### Output IP

**Who owns AI-generated content?**
- In the US, copyright requires human authorship. Purely AI-generated content (no human creative input) is not copyrightable. Works with substantial human creative contribution can be copyrightable — the human element must be meaningful, not just prompting.
- Practically: if your product generates content for customers, they likely cannot claim copyright in purely AI-generated portions. This affects how you describe deliverables in customer contracts.

**Infringement in outputs:**
- Models can reproduce training data — this is documented and exploited (memorization)
- Deploying a model that outputs substantial portions of copyrighted works creates infringement liability for the deployer, not just the model provider
- API provider indemnification provisions vary significantly; read and negotiate them

**Trade secret protection for AI systems:**
- Training data, model weights, fine-tuning data, prompt systems can be trade secrets if maintained as confidential
- Requires: reasonable secrecy measures (access controls, NDAs, restricted distribution) and commercial value derived from secrecy

### IP in Customer Contracts

When you provide AI-generated outputs to customers, your contracts should address:
- Who owns the output (typically customer, with a license back to provider for improvement)
- Accuracy representations — avoid representing AI output as independently verified
- Downstream use restrictions — if you're using third-party models, your usage terms may restrict customer uses
- Indemnification scope — will you indemnify customers against IP claims arising from your AI output?

## Privacy Law Applied to AI

AI systems are voracious data consumers. Every personal data input into an AI system is subject to applicable privacy law.

### Data Minimization and Purpose Limitation

**GDPR and CCPA principles:** Collect only what you need, use it only for stated purposes. AI creates pressure in both directions:
- Training data needs are extensive (pressure to collect more)
- Privacy law demands minimization (legal pressure to collect less)

**The conflict:** You cannot use personal data collected for "service delivery" to train an AI model without separate disclosure and consent — using data for training is a different purpose.

**Practical guidance:**
- Audit what personal data flows into AI systems (training, fine-tuning, inference, logging)
- Confirm legal basis for each use under GDPR (consent, legitimate interest, contractual necessity)
- Update privacy notices to disclose AI data uses before deploying
- Provide opt-out mechanisms where required (California CCPA AI profiling disclosures)

### Special Category and Sensitive Data

Extra caution for data that carries heightened protection:
- Health/medical data (HIPAA in US, Art. 9 GDPR in EU) — AI in healthcare requires specific controls and often explicit consent
- Financial data (GLBA, state laws) — AI-driven credit decisions face FCRA and ECOA constraints
- Biometric data (Illinois BIPA and many US state laws) — facial recognition and voice AI face significant class-action exposure
- Children's data (COPPA, FERPA) — AI systems must age-gate or exclude

### Automated Decision-Making Rights

**GDPR Article 22:** Data subjects have the right not to be subject to decisions based solely on automated processing that produce significant effects. This includes explicit right to human review, explanation of logic, and ability to contest.

**US:** No federal equivalent (yet). California CPRA created limited rights. Federal rulemaking ongoing.

**Practical implication:** For decisions that significantly affect people — credit, insurance, employment, housing, healthcare — build in human review requirements, explanation capability, and audit trails.

### Cross-Border Data Transfer

AI providers are often US-based; customers are global. Sending EU personal data to US AI providers requires:
- Standard Contractual Clauses (SCCs) with the provider
- Transfer impact assessment for high-risk transfers
- Confirm provider has appropriate safeguards

## Discrimination and Bias Liability

AI can encode and amplify discrimination at scale — and existing law prohibits it.

**Applicable law (US):**
- *EEOC guidance:* Employers using AI for hiring, promotion, or performance management are liable for disparate impact on protected classes, even if the AI system is from a third party
- *CFPB:* AI-driven credit and lending decisions must comply with ECOA and FCRA; explainability is required; "black box" is not a defense to adverse action notice obligations
- *FHA:* AI in tenant screening or housing allocation must comply with Fair Housing Act
- *ADA and state equivalents:* AI accessibility requirements for hiring and customer-facing tools

**The EU AI Act tier for high-risk AI:**
- Hiring, credit, education, law enforcement, critical infrastructure — these are high-risk use cases
- Require conformity assessment, technical documentation, human oversight, transparency
- Applying to EU users regardless of where the company is based

**Practical steps:**
- Bias audit before deploying AI in any consequential decision (hiring, credit, insurance, housing)
- Document disparate impact testing and results
- Build human review into adverse outcomes
- Assess third-party AI vendor's bias testing practices and obtain contractual representations

## The EU AI Act (2024)

In force August 2024, with phased applicability through 2027. Applies to any company deploying AI systems to EU users.

**Risk tiers:**

*Unacceptable risk (prohibited):*
- Real-time biometric surveillance in public spaces (with narrow exceptions)
- Social scoring by governments
- Manipulation of vulnerable groups
- Subliminal techniques circumventing free will

*High risk (regulated):*
- Critical infrastructure
- Education and vocational training
- Employment and HR management
- Essential services (credit, insurance, health)
- Law enforcement
- Migration and border control
- Administration of justice

*Limited risk (transparency obligations):*
- Chatbots must disclose they are AI
- Deepfakes must be labeled
- AI-generated content must be disclosed (under certain conditions)

*Minimal risk (no obligations):* Most AI (spam filters, recommendation systems, etc.)

**For companies in high-risk categories:**
- Register in EU database
- Conduct conformity assessment
- Maintain technical documentation
- Implement human oversight
- Ensure explainability and audit logging
- Establish post-market monitoring

**For general-purpose AI (GPAI) providers (frontier model companies):**
- Model documentation requirements
- Copyright compliance policy
- Summary of training data
- For very capable models: additional safety evaluations, incident reporting

## Emerging US AI Regulation

No comprehensive federal AI law as of 2025, but significant activity:

**FTC:** Broad authority over unfair and deceptive practices. Has signaled it will pursue:
- Deceptive AI-generated content
- AI that manipulates consumers
- Privacy violations in AI training
- False performance claims about AI

**CFPB:** AI in lending — final rule-making ongoing on explainability, adverse action notices, model auditing.

**EEOC:** AI in employment — technical assistance guidance (2023); enforcement actions ongoing.

**FDA:** AI/ML in medical devices — regulatory framework for software as a medical device (SaMD); cleared products face post-market monitoring requirements.

**State laws:** Colorado (AI consumer protection), Illinois (BIPA, AI in hiring), New York City (Local Law 144 — bias audit for AI hiring tools), California (CPRA AI profiling), Texas, Virginia, and others with emerging requirements.

**International:** Canada (AIDA proposed), UK (sector-led approach, no comprehensive law), Brazil (AI Bill), China (comprehensive regulations in force).

## Contracting for AI

Key provisions to include or negotiate in AI vendor agreements:

**Data handling:**
- Does the vendor train on customer inputs by default? Opt-out available?
- Data residency and jurisdiction
- Deletion rights and timelines

**Output ownership:**
- Who owns outputs generated using the vendor's model?
- IP indemnification — will the vendor defend you against third-party IP claims arising from outputs?

**Service levels:**
- Uptime SLA for AI inference
- Latency guarantees (relevant for customer-facing applications)
- Model version stability (what happens when they update the model?)

**Security and compliance:**
- SOC 2 / ISO 27001 attestations
- GDPR DPA (Data Processing Agreement) — mandatory for EU data
- Breach notification timeline

**Liability:**
- Cap on damages from AI errors
- Exclusion of consequential damages
- Indemnification for regulatory fines arising from vendor's compliance failures

## The Minimum Governance Posture

For a company deploying AI today:

1. **AI use policy:** Approved tools, data classification rules, output review requirements — see `ai_and_automation.md`
2. **Privacy notice update:** Disclose AI uses of personal data before they happen
3. **Vendor DPA review:** Ensure GDPR-compliant data processing agreements with all AI vendors
4. **IP clearance for training data:** If training models, document the legal basis for each data source
5. **High-risk use case audit:** Identify any AI in hiring, credit, or other regulated domains; assess bias and explainability requirements
6. **EU AI Act applicability check:** Are any products or customers in EU? If yes, classify the AI systems by risk tier and begin compliance planning

The law will continue to evolve faster than annual legal review cycles. Designate an owner (General Counsel, Chief Privacy Officer, or external counsel) with a standing brief to monitor and report AI regulatory developments quarterly.

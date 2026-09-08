# AcmeCorp Data Residency Policy DRP-7

**Owner:** Data Protection Office  
**Applies to:** Customer Data processed by third-party hosted services  
**Classification:** Internal - Controlled

## Objective

DRP-7 controls where Customer Data may be stored, accessed, backed up, and otherwise processed. It supports AcmeCorp's customer commitments and regulatory transfer obligations. The policy applies to production data, support copies, diagnostic extracts, disaster-recovery replicas, and personal data contained in service telemetry. Aggregated data is outside scope only when re-identification is not reasonably possible.

## Approved Processing Region

Customer Data used with third-party hosted services may be processed only within the European Economic Area. A vendor's corporate location, billing address, or primary data-center label does not establish compliance; all subprocessors and remote support locations with access to Customer Data must be considered. Encryption does not by itself change the location of processing.

Cross-border processing outside the EEA is permitted only as a documented exception. Before such processing begins, the contract owner must ensure that applicable Standard Contractual Clauses are executed, a transfer impact assessment is completed, and the AcmeCorp Data Protection Officer gives written approval. All three controls are mandatory. General assurances, industry certifications, or a vendor statement that it uses reasonable safeguards are not substitutes.

## Subprocessor Governance

Contracts must identify the authorized processing region and require advance notice of a new material subprocessor. The vendor must remain responsible for subprocessor obligations and provide enough information for AcmeCorp to assess processing location and function. A general authorization mechanism may be used only when it remains consistent with the EEA-only rule and preserves AcmeCorp's right to object on documented data protection grounds.

The service owner must review the current subprocessor list before onboarding and at least annually. Material changes are routed to Privacy and Security. Emergency replacement of a subprocessor may proceed only under the incident process and does not waive transfer requirements.

## Operations, Retention, and Exceptions

Support teams should use masked or synthetic data where practical. Production exports must have an owner, purpose, approved destination, and deletion date. Backup retention must align with the Records Schedule, and restored copies remain subject to this policy.

Exception requests must name the countries, entities, data categories, access method, duration, and business need. Approval expires after twelve months or on a material processing change, whichever occurs first. Procurement, Security, or a business executive cannot approve an exception on behalf of the Data Protection Officer. Suspected non-compliance must be reported to the Privacy Operations queue and remediated before contract signature or production onboarding.
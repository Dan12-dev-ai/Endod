# Endod Health — Tena Medhin (Health Insurance) Integration & Business Model

> **Companion README** to the main [README.md](./README.md). It explains how the
> Endod Health platform should handle patients who are members of Ethiopia's
> public health insurance (Tena Medhin / የጤና መድህን) and of the newer digital
> private micro-insurance products, and it lays out the business opportunities
> and profit models available on top of that capability.
>
> **Status:** design + strategy document. It is grounded in what the repository
> actually implements today (see [docs/architecture.md](docs/architecture.md));
> anything labelled "planned" is not yet in the code.

---

## 0. Table of contents

1. [What "Tena Medhin" means in Ethiopia](#1-what-tena-medhin-means-in-ethiopia)
2. [What Endod Health is today](#2-what-endod-health-is-today)
3. [How to handle users who have insurance](#3-how-to-handle-users-who-have-insurance)
4. [Business opportunities](#4-business-opportunities)
5. [Business models and how to get profit](#5-business-models-and-how-to-get-profit)
6. [Implementation roadmap](#6-implementation-roadmap)
7. [Risks, constraints and limitations](#7-risks-constraints-and-limitations)
8. [Success metrics](#8-success-metrics)

---

## 1. What "Tena Medhin" means in Ethiopia

"Tena Medhin" (የጤና መድህን) is the Amharic term for health insurance. In
Ethiopia it refers to two overlapping layers:

### 1.1 Public framework — Ethiopian Health Insurance Service (EHIS)

Two programs prevent citizens from facing catastrophic out-of-pocket bills:

- **Community-Based Health Insurance (CBHI)** — the widespread branch.
  - Audience: informal sector — rural farmers, pastoralists, urban informal
    workers.
  - Registration & premiums: households register through their local **Kebele**
    administration and pay a small, affordable **annual premium** into a pooled
    district fund.
  - Indigent subsidy: the poorest households are **fully subsidised** by the
    government.
  - Care: members carry a physical or digital insurance card and receive care at
    public health centres/hospitals in their designated network instead of
    paying cash.

- **Social Health Insurance (SHI)** — the formal workforce branch.
  - Audience: civil servants, government employees, workers in formal private
    enterprises.
  - Premiums: a **salary-deducted percentage**, deducted monthly from the
    employee's pay.

**Coverage model — "negative list":** almost all essential medical needs are
covered unless specifically excluded. Covered: outpatient (consultations, labs,
X-ray, ultrasound, CT, specialist checks), inpatient (stays, minor/major/complex
surgery including cardiac/neurosurgery, ICU), and **500+ essential medicines**.
Excluded: cosmetic / non-essential treatments.

### 1.2 Digital private layer — medhinLink / "Tele Medhin"

Private micro-insurance distributed via **Ethio Telecom's Telebirr Super App**:

- No medical exams or paperwork.
- Annual plans starting around **1,100 ETB/year**, purchased on the phone.
- Acts as a **safety net**: payouts for hospital income loss, funeral support
  and school-fee assistance — **not** direct clinic billing.

### 1.3 What this means for a platform like Endod

| Dimension | CBHI | SHI | medhinLink / Tele Medhin |
| --- | --- | --- | --- |
| Sector | Informal / rural | Formal / corporate | Anyone with a phone |
| Enrolment | Kebele | Employer payroll | Telebirr app, self-serve |
| Premium | Flat annual | % of salary | ~1,100 ETB/year |
| Indigent | Fully subsidised | n/a | n/a |
| Care access | Designated public network | Contracted providers | Cash at point of care, then payout |
| Billing | Cashless at network facilities | Cashless/claim at contracted providers | Reimbursement / payout, not direct billing |
| Coverage | Negative list (essential) | Negative list (essential) | Hospitalisation income loss, funeral, school fees |

**Key insight:** CBHI/SHI are *cashless-at-network* schemes; medhinLink is a
*payout* product. Endod must treat them differently — one is a payment method,
the other is a claim trigger.

---

## 2. What Endod Health is today

Endod Health (engineering name DEDAN Health) is an Ethiopian health-navigation
platform. The verified, running parts are:

- **Patient portal** (`web-portal/`, Next.js) + **mobile app** + **WhatsApp/SMS**
  (`messaging-backend/`) + **clinic console** (`clinic-dashboard/`).
- **AI symptom triage & navigation** (FastAPI, `backend-v2/`): text/image/voice
  transcript -> structured, safety-validated clinical document, with red-flag
  escalation. Not a diagnostic system.
- **Partner hospital directory & booking**: in-person and video (Jitsi) visits,
  paid from the patient's **Endod balance**.
- **Digital Health Card**: a signed card carrying the patient's `DE######` ID,
  verifiable by a hospital desk via QR (`GET /cards/{dedan_user_id}/verify`).
- **Wallet**: deposits through **Chapa** (Ethiopian payment gateway), balance in
  santim, with a flat service fee (`SERVICE_FEE_FLAT_SANTIM`, default 5 birr)
  and a percentage fee (`SERVICE_FEE_PERCENT_BP`).
- **Appointments & reminders**: scheduling, SMS/email reminders, cancellation
  and refund rules.
- **Emergency navigation**: national numbers (907/991/939) plus nearest partner
  hospitals with ambulance/emergency.
- **Medical records, inbox, notifications, profiles, consent.**

**Today there is no insurance handling at all** — search of the repository
returns no `insurance`, `CBHI`, `SHI`, `kebele`, `premium` or `medhinLink`
code. Insurance is a greenfield capability, which is both the gap and the
opportunity.

Amharic (`am`) is already a supported language in triage (`Language.AM`), and
the platform is already Ethiopia-focused (Chapa, Birr, `Africa/Addis_Ababa`,
Ethiopian emergency numbers), so Tena Medhin support fits the existing product
identity.
---

## 3. How to handle users who have insurance

This section is the implementation playbook. It is written against the existing
architecture (identity/health-data separation, partner hospitals, wallet,
cards, records, inbox).

### 3.1 Capture & store insurance identity (onboarding + profile)

Add an `InsuranceProfile` table, kept **separate** from `HealthProfile` (the
codebase already separates identity, profile, preferences, health profile and
consent on purpose — insurance is personal/financial data with its own access
and retention rules).

Fields:

- `insurance_type`: `none | cbhi | shi | medhinlink | private_other`
- `member_id`, `policy_number`, `scheme_name`
- `cbhi`: `kebele`, `woreda`, `district_fund`, `enrolment_year`, `indigent` (bool)
- `shi`: `employer`, `payroll_number`, `contribution_rate`
- `medhinlink`: `telebirr_msisdn`, `plan_tier`, `plan_start`, `plan_expiry`
- `card_image_id` (uploaded via existing image service), `verified_at`, `verified_by`
- `preferred_facility_network` (woreda-designated for CBHI)

Onboarding (`/onboarding`) should ask: "Do you have Tena Medhin?" with the three
branches above, and let the user upload their card photo. Verification is
async: `verified = false` until a partner/agent confirms.

### 3.2 Verify the card

- **CBHI:** cross-check member ID + kebele against the district fund / EHIS.
  In practice this requires a **partnership with EHIS or the woreda office**;
  until then, treat the uploaded card as "self-declared, pending verification"
  and show a "pending" badge.
- **SHI:** verify against employer payroll / the SHI scheme.
- **medhinLink:** verify via Telebirr/insurer API using MSISDN + policy number.

Expose verification status on the digital card: `GET /users/me/card` should
return an `insurance` block (`type`, `member_id`, `status: verified|pending`,
`network`). The public verification endpoint
`GET /cards/{dedan_user_id}/verify` should expose only what a hospital desk
needs: `insured: true/false`, `scheme`, `member_id`, `status` — never health
data.

### 3.3 Eligibility & coverage check (the "negative list" engine)

Build a small **Coverage Service**:

- Input: `(insurance_type, service_code, facility_id, is_cosmetic)`.
- Rule: essential services are covered unless on the exclusion list (cosmetic /
  non-essential). So `covered = not excluded AND in_network(facility)`.
- Output: `{ covered: bool, patient_share_santim, insurer_share_santim,
  copay_santim, reason }`.

Service codes should map to the existing care departments
(`DEPARTMENT_GENERAL`, `MATERNAL`, `PEDIATRIC`, `CARDIOLOGY`, `RESPIRATORY`,
`EMERGENCY`) plus procedures (surgery, imaging, labs) and medications.

For **medhinLink**, coverage is not clinic billing — instead the service returns
`payout_eligible: true` with the qualifying event types (hospitalisation,
funeral, school fees) and the payout amounts per plan tier.

### 3.4 Facility network routing

- **CBHI members** must be routed to the designated public network in their
  woreda. The care directory should filter `partners.listed()` to in-network
  facilities first, and warn when an out-of-network (private) hospital is
  selected ("This facility may not be covered by your CBHI; you may pay
  out of pocket").
- **SHI members** see contracted providers.
- **medhinLink members** see all facilities (they pay cash and claim later).

The existing `care_navigation` ranking (by distance/clinical relevance) should
add an `in_network` boost for insured users.

### 3.5 Booking & quoting (coverage-aware)

Extend `hospital_bookings.quote()` and the
`GET /users/me/hospital-bookings/quote` endpoint to accept the user's insurance
context:

```
quote = { hospital_price, endod_fee, total, insurance: { type, covered,
          insurer_share, patient_share (copay), out_of_pocket } }
```

- If in-network and covered: `out_of_pocket = copay` (often 0 for CBHI
  essential care at public facilities); Endod collects the insurer share as a
  **claim**, not from the wallet.
- If not covered / out-of-network: full price from wallet (current behaviour).
- **Indigent CBHI members**: `out_of_pocket = 0` and no premium; optionally
  waive the Endod service fee (configurable per partnership).

The booking transaction (`book`) must branch:

1. **Cashless path (CBHI/SHI in-network):** create appointment + a `Claim`
   record (status `draft`) instead of charging the wallet; emit
   `appointment.requested` to the hospital with the member ID so the hospital
   can bill the scheme; hospital confirms/completes as today; on `completed`,
   submit the claim.
2. **Cash path (medhinLink / out-of-network / uninsured):** charge wallet as
   today; on hospitalisation, create a payout claim to medhinLink.

### 3.6 Claims management (new module: `insurance_claims.py`)

New table `InsuranceClaim`:

- `id`, `user_id`, `appointment_id`, `insurance_type`, `member_id`
- `service_codes`, `claimed_amount_santim`, `approved_amount_santim`
- `status`: `draft | submitted | under_review | approved | paid | rejected | appealed`
- `documents` (receipt/record IDs), `submitted_at`, `resolved_at`, `rejection_reason`
- `payout_reference` (for medhinLink)

Endpoints:

- `GET /users/me/claims` — list
- `GET /users/me/claims/{id}` — detail + timeline
- `POST /users/me/claims/{id}/submit` — submit (attaches records/receipts)
- `POST /users/me/claims/{id}/appeal`

Documents come from the existing **records** module (diagnosis, prescriptions,
receipts) plus uploaded images. Status changes notify via the existing
**inbox/notifications** system ("Your CBHI claim for visit at X has been
approved").

For **medhinLink**, claims are payout requests triggered by a qualifying event
(hospitalisation). Endod should auto-create a draft claim when an appointment
is marked `completed` with an inpatient flag, and prompt the user to add
supporting docs (discharge summary, receipt).

### 3.7 Premiums & enrolment support

- **CBHI enrolment helper:** guide the user through kebele registration,
  show the annual premium for their woreda, allow paying the premium via the
  Endod wallet/Chapa, and remind annually. For indigent households, skip
  payment and mark `subsidised`.
- **SHI:** show contribution rate and payroll deduction; no collection needed
  (employer handles it), but Endod can show "your SHI is active".
- **medhinLink:** deep-link to Telebirr for purchase/renewal; track expiry
  and remind 30 days before.

This positions Endod as the **digital front door** to both public and private
insurance.

### 3.8 Data separation, consent & privacy

Follow the existing pattern: identity != health data != insurance data. Add a
consent flag `consent_insurance_verification` and `consent_claim_submission`.
Claims require the user's explicit consent to share medical records with the
insurer. Audit every claim access (the codebase already has an audit-log
concept in `database_security.py`).

### 3.9 UX surfaces

- **Profile/Settings:** "My Insurance" card with scheme, member ID, status,
  expiry, edit.
- **Booking quote:** coverage badge ("Covered by CBHI — 0 ETB out of pocket"
  or "Not covered — 450 ETB").
- **Digital card:** insurance badge + member ID + QR.
- **Inbox:** claim status updates, premium renewal reminders, medhinLink
  expiry.
- **Clinic console:** a "Claims" tab for hospital staff to confirm service
  delivery for cashless visits.

### 3.10 What is NOT in scope (yet)

- Real EHIS/Telebirr API integration (needs partnerships).
- Automated adjudication (insurer decides).
- Cross-border / non-Ethiopian schemes.

---

## 4. Business opportunities

The platform already has the hard parts: patient identity, verified card,
wallet, partner hospitals, booking, records, notifications, Amharic UI, and
Chapa payments. Adding insurance turns Endod from a "pay-per-visit" tool into
the **financial layer of Ethiopian healthcare**.

### 4.1 Digitising public insurance (CBHI/SHI)

- **Digital enrolment & premium collection** for CBHI: millions of informal
  households enrol via kebele today with paper; Endod can be the digital
  channel, collecting premiums via Chapa/Telebirr and issuing a digital card.
- **Indigent identification & subsidy flow:** help woredas identify and enrol
  subsidised households, reducing leakage.
- **SHI corporate portal:** employers manage employee coverage, view utilisation,
  integrate with payroll.

### 4.2 Claims facilitation (cashless care)

- Become the **claims router** between patients, hospitals and EHIS: hospitals
  get faster, verified reimbursement; patients get cashless care; EHIS gets
  cleaner data. Charge a processing fee per claim.
- Reduce hospital bad debt and administrative cost — a strong B2B value
  proposition for partner hospitals.

### 4.3 Private micro-insurance distribution

- **Cross-sell medhinLink/Tele Medhin** and other private products to Endod
  users; earn commission per policy.
- **Bundle:** "Endod Care Plan" = navigation + telehealth + micro-insurance,
  sold as one subscription.

### 4.4 Telehealth for the underserved

- CBHI members in woredas without specialists can use Endod video visits;
  Endod bills the scheme. This is a high-margin, high-impact service.

### 4.5 Pharmacy & medication

- Coverage-aware pharmacy guidance: check whether a medicine is on the
  500+ essential list and covered; suggest generics; partner with pharmacies
  for fulfilment and discounts.

### 4.6 Data & population health (with consent)

- Anonymised utilisation, disease burden and cost analytics for EHIS,
  employers, NGOs and researchers — a recurring revenue stream and a public
  health asset.
- Risk stratification for chronic care (already modelled in
  `ChronicCareData`).

### 4.7 Emergency & ambulance

- Insurance-authorized ambulance dispatch and cashless emergency care at
  partner hospitals — premium service for SHI/corporate clients.

---

## 5. Business models and how to get profit

Recommended: a **hybrid** of transaction fees + SaaS + distribution, phased in.

### 5.1 Transaction / claims processing fee (core, near-term)

- Charge **2–5% or a flat fee per claim** processed/settled (both CBHI/SHI
  cashless visits and medhinLink payout requests).
- Plus the existing **service fee on wallet deposits** (5 birr flat + 2%).
- Indigent CBHI visits: waive or reduce the fee (subsidised by government
  contract or CSR).

### 5.2 SaaS for clinics & hospitals (recurring)

- Monthly license for the **clinic console** + claims module + analytics.
- Tiers: Basic (triage queue) / Pro (claims + analytics) / Enterprise
  (multi-site + API).
- Existing `pricing_models.py` / `billing_system.py` already sketch
  subscription tiers and Ethiopia bank config — reuse and extend.

### 5.3 B2B / employer SHI (PEPM)

- Per-employee-per-month fee for corporate clients: employee app, coverage
  management, telehealth, analytics dashboard.
- High LTV, low churn, predictable revenue.

### 5.4 Government / EHIS contracts (B2G)

- Per-woreda or per-member platform fee for digital enrolment, premium
  collection and claims routing.
- Tenders/contracts; longer sales cycle but large scale and defensible.

### 5.5 Insurance distribution commission

- Commission on medhinLink and other private policies sold through Endod
  (CPA-based, recurring on renewals).

### 5.6 Telehealth revenue share

- Revenue share on video visits (existing Jitsi integration) billed to
  schemes or patients.

### 5.7 Premium financing (micro-lending)

- Allow CBHI households to pay annual premiums in instalments via Endod
  wallet; charge a small financing fee. Improves enrolment and retention.

### 5.8 Data products (long-term)

- Anonymised, consented population health reports sold to EHIS, NGOs,
  researchers, pharma (with strict governance).

### 5.9 Bundled consumer subscription ("Endod Care Plan")

- Monthly/annual subscription: navigation + telehealth credits +
  micro-insurance + pharmacy discounts. Appeals to urban informal workers
  not on CBHI.

### 5.10 Unit economics (illustrative)

| Lever | Value |
| --- | --- |
| Service fee per booking | 5 birr + 2% |
| Claims processing fee | 2–5% of claim |
| Clinic SaaS | monthly per clinic |
| Employer PEPM | per employee per month |
| EHIS contract | per member per year |
| Commission on micro-insurance | % of premium |
| CAC target (urban) | low (WhatsApp + referrals) |
| Retention driver | wallet balance + insurance status + records |

---

## 6. Implementation roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | `InsuranceProfile` model, onboarding capture, card badge | planned |
| 1 | Verification flow (self-declared -> verified), `GET /users/me/card` insurance block | planned |
| 2 | Coverage service (negative list), in-network routing in care directory | planned |
| 3 | Coverage-aware quotes (`hospital_bookings.quote`), copay display | planned |
| 4 | Cashless booking path + `InsuranceClaim` model + claim endpoints | planned |
| 5 | Inbox/notifications for claim status, premium reminders | planned |
| 6 | EHIS/Telebirr integrations (needs partnerships) | planned |
| 7 | Clinic console "Claims" tab | planned |
| 8 | Analytics & B2B dashboards | planned |

Prerequisites from the existing roadmap that insurance **depends on**:

- Authentication & authorization (no auth today — insurance data cannot ship
  without it).
- Persistence hardening & audit log (claims need an append-only audit trail).
- Real evidence/retrieval not required, but records module must be solid.

---

## 7. Risks, constraints and limitations

- **No auth today** (`docs/security.md`): insurance and claims data are
  sensitive; this is a hard blocker for any real deployment.
- **EHIS has no public API** that we can assume; integration requires a
  government partnership and may take months.
- **medhinLink is a payout product, not cashless billing** — UX must set
  expectations (patient pays cash, then claims).
- **Indigent handling** must be designed with woreda offices to avoid
  exclusion or fraud.
- **Regulatory/compliance**: data protection, medical liability, insurance
  distribution licensing. The repo explicitly makes no compliance claims.
- **Fraud risk**: fake claims, duplicate enrolment — needs verification and
  audit.
- **Currency/fee sensitivity**: keep fees small; the informal sector is
  price-sensitive (CBHI premiums are deliberately low).

---

## 8. Success metrics

- % of users with a verified insurance profile.
- Claim approval rate and time-to-settlement.
- Out-of-pocket spend reduction for insured users.
- Premium collection volume (CBHI) and renewal rate.
- Number of partner hospitals offering cashless visits.
- Revenue mix: transaction fees vs SaaS vs distribution vs data.
- NPS among insured users and hospital partners.

---

> Endod Health provides health education and navigation. It is not a substitute
> for professional medical advice, diagnosis, or treatment. Insurance coverage
> decisions are made by the relevant scheme (EHIS / insurer), not by Endod.


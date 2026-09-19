---
domain: operations
topic: quality
company: Boeing
year: 2018
failure_type: [quality_process, safety_culture, cost_pressure, regulatory_capture, outsourcing]
---

# Boeing 737 MAX MCAS Failures (2018–2019)

## Situation

In 2011, Airbus announced the A320neo — a fuel-efficient narrow-body jet that threatened Boeing's market position. Rather than develop a new aircraft, Boeing decided to re-engine the existing 737 platform to match the A320neo's economics. The new engines were larger and needed to be positioned differently on the wing, which altered the aircraft's flight dynamics. Boeing developed MCAS (Maneuvering Characteristics Augmentation System) to automatically correct for this, preventing a tendency to pitch up at high angles of attack. To avoid requiring pilots to undergo expensive simulator training — a key cost advantage Boeing was selling to airlines — MCAS was not disclosed to pilots in training materials.

## What Happened

Lion Air Flight 610 crashed into the Java Sea on October 29, 2018, killing 189 people. Ethiopian Airlines Flight 302 crashed on March 10, 2019, killing 157 people. Both crashes were caused by MCAS activating repeatedly based on faulty sensor data and pilots being unable to overcome the system. All 737 MAX aircraft were grounded globally for 20 months. Boeing's CEO was fired. Boeing paid $2.5 billion in a settlement with the Department of Justice, and set aside $20 billion+ for compensation, rework, and delivery delays.

## Root Cause

MCAS was designed with a single point of failure — a single angle-of-attack sensor — despite Boeing's standard redundancy requirements for safety-critical systems. The decision was made, and documented internally, to use a single sensor to save $80,000 per aircraft, which would have required dual-sensor training. Internal communications showed Boeing engineers expressing concern about MCAS and being overruled; employees describing pressuring regulators; and managers celebrating hiding MCAS from pilots. Cost and schedule pressure, applied consistently, overrode engineering safety standards.

## Key Decision Failures

- **Safety-critical system designed to single-sensor failure**: MCAS activated on data from a single angle-of-attack sensor; a single faulty sensor could — and did — trigger uncontrollable nose-down input
- **System hidden from pilots to avoid training costs**: Omitting MCAS from training materials was a commercial decision, not a safety decision; pilots who knew MCAS existed could have diagnosed and countered it
- **Cost pressure institutionalized over safety culture**: Internal emails showed engineers raising safety concerns that were dismissed with reference to schedule and cost; the organizational signal was that safety concerns were obstacles
- **Regulatory capture**: Boeing engineers were embedded in the FAA's certification process for the 737 MAX, effectively self-certifying elements of the aircraft's safety
- **Supplier quality degraded by outsourcing pressure**: Multiple quality issues in Boeing's supply chain traced to cost-driven outsourcing decisions that reduced Boeing's ability to control manufacturing standards

## Lessons

1. **Safety-critical system design is not a cost optimization**: The $80,000 savings per aircraft that justified a single-sensor MCAS design cost Boeing $20 billion and 346 lives. Cost-benefit analysis applied to safety-critical system redundancy is a category error.
2. **When engineers stop speaking up, the safety culture is already broken**: The documented pattern of Boeing engineers' concerns being dismissed indicates that the informal norm — "concerns are obstacles" — had already replaced the formal safety culture long before the crashes.
3. **Regulatory independence requires organizational independence**: Regulators who are embedded in, or funded by, the entities they regulate cannot provide independent safety oversight. The structure of certification matters as much as the standards.
4. **Schedule and cost pressure compound linearly; safety failures are nonlinear**: Pressure applied for years produces incremental schedule gain; a single safety failure produces catastrophic, non-recoverable loss.

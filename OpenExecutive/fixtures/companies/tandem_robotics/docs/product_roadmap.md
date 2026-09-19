# Tandem Robotics — Product Roadmap

Owner: **Jordan Avery (CEO, acting Head of Product & Engineering)**

## Tandem V1 (deployed)
General-purpose warehouse humanoid, leased as a service, working in human-designed
aisles with no fixed infrastructure.

- **Autonomy stack** with remote-teleop fallback, so the customer needs no robotics
  team on site.
- Fleet telemetry and over-the-air updates across all deployed robots.
- Near-term priorities:
  - **Autonomy-rate improvement** (from ~82% toward 95%) — directly cuts teleop
    cost-to-serve and is the single biggest lever on RaaS unit economics.
  - **Pick/place reliability and recovery** so an exception does not become a stop.
  - **Fleet uptime and remote-ops tooling** to hold the SLA across more sites.

## Safety case for shared floors
A robot sharing a floor with people earns trust on safety every shift, so the
**human-robot collaboration safety case** is treated as **part of the product**,
not an afterthought — speed/force limits, clearance behavior, and auditable safety
telemetry feed both the OSHA posture (Legal) and customer trust.

## V2 dexterous-manipulation platform (decision pending)
A next-generation platform with materially better manipulation. The open decision
this year is **build now vs. defer** until the deployed fleet reaches
gross-margin-positive.

- A board decision memo is in progress, led by Product with Finance and Strategy
  input.
- Tension: committing capital to V2 now widens capability but extends the runway
  risk before per-robot margins turn positive.

## Product principles
- **Uptime is the product.** Every program trade-off is checked against deployed-
  robot uptime and cost-to-serve first.
- **Autonomy over dexterity theater.** We raise the autonomy rate and reliability
  rather than chase manipulation demos that don't add billable robot-hours.
- **Don't ship safety debt onto a warehouse floor.**

## Competitive product watch
We maintain capability teardowns against **Figure**, **Agility (Digit)**, and
**Apptronik (Apollo)**. New competitor autonomy, throughput, or manipulation claims
should refresh the relevant teardown and, when material, route a recommendation to
Product.

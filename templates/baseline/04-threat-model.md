# Threat model (as-is): {{product name}}

<!-- MOADIX phase B. Threats to the CURRENT system, each with its current status:
mitigated | partial | open | unknown. Anything not "mitigated" also goes in sdlc/B-known-gaps.md
as an open finding. -->

## Trust Boundaries

| ID | Boundary | Description |
|----|----------|-------------|
| TB-1 | {{boundary}} | {{where untrusted input enters, path:line}} |

### SEC-001 - {{threat}}

- **Trust boundary:** TB-1
- **STRIDE:** {{Spoofing | Tampering | Repudiation | Information Disclosure | Denial of Service | Elevation of Privilege}}
- **Threat:** {{what could happen}}
- **Current status:** {{mitigated | partial | open | unknown}}
- **Evidence:** {{path:line of the control, or of the exposed code}}
- **Mitigation requirement:** {{what a fix would require}}
- **Owner phase:** {{5 | 7 | 9}}

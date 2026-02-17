# Infrastructure Analysis

## Network Topology

Compromised infrastructure includes:

### Command and Control Servers

1. Primary C2: 198.51.100.42
   - Hosted in Country-A
   - Registered to shell company
   
2. Backup C2: 203.0.113.55
   - Hosted in Country-B
   - Uses domain fronting

## Mitigation

Block the following at firewall:
- 198.51.100.0/24
- 203.0.113.0/24

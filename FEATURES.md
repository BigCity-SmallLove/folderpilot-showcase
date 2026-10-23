# Features and client use cases

| Capability | Example customer task |
| --- | --- |
| Batch replacements, prefixes/suffixes, numbering and Python regex | Standardize agency deliverable filenames |
| Organize by extension, modification month or byte-size group | Prepare a supplier drop folder for handover |
| Extension/size/date filters and optional recursion | Limit a job to the explicitly approved subset |
| SHA-256 duplicate groups | Audit repeated exports without deleting records |
| Verified directory snapshots | Copy an approved working set and verify byte integrity |
| Version-preserving incremental sync | Deliver new and changed files while preserving earlier recipient versions |
| Configurable notify-only polling | Notice changes in a selected intake directory during an active session |
| JSON rules, complete plan export and HTML records | Reuse a client workflow and explain what happened |
| Dry Run, confirmation, exclusive destinations and recovery | Review changes and undo eligible operations without overwrites |

Customization can add client naming conventions, validation, additional grouping rules or report layouts. Full-system backup, ACL/alternate-stream preservation, destructive mirroring, real-time filesystem transactions, automatic deletion, remote administration, background services and startup integration are outside v0.1.1 scope.

# Bounded recursive watch design

Status: implementation in progress. This record is not a claim that recursive
watching is available. Existing explicit watch behavior remains the default.

The opt-in interface is `--watch-recursive` with existing explicit `--watch-dir`
roots. Initial limits: eight roots, 256 watched identities per generation
(including root-parent sentinels), depth 32, 8192 examined entries per scan or
verification pass, and eight reconciliation attempts. Excluded discovered
directory basenames: .git, .honk, target, .build, .toolchain. Explicit roots
are intentional selections and override discovered-name exclusions. Limits
reject the complete attempt rather than advertise partial coverage.

## Identity and no-follow traversal

A path list alone cannot bind an inotify watch to the directory opened during
scanning: a child can change between lookup and registration, including ABA
replacement. Add an independent goose-watch `open_set_fds` interface first.
It borrows 1..256 already-open directory descriptors during registration,
uses controlled `/proc/self/fd/N` aliases, and keeps the existing WatchSet
ownership, index and loss rules. Existing path APIs remain unchanged.

Honk opens roots component by component with no-follow descriptor-relative
operations, then scans through retained directory descriptors. Directory
identity, parent relationships and raw basenames remain retained until a
generation retires. No untrusted tree symlink is traversed; trusted procfd
registration does deliberately follow its controlled numeric alias. This is
not filesystem confinement. Concurrent renames can move retained directories
outside their old topology; inotify does not report mounts over watched paths.

Retaining a root fd can defer its IN_DELETE_SELF/IGNORED until the fd closes.
Therefore each explicit root has a watched parent sentinel and an exact raw
basename/identity binding. Explicit root/sentinel move, removal or identity
failure stops the session; discovered directory changes request reconciliation.
The root-parent sentinels count against the 256 identity limit. An identity
shared between a sentinel and included directory has both roles; aliasing or
overlapping explicit roots must have an explicit deduplication/rejection policy
before the implementation is accepted.

## Generations and coverage

Use two named WatchSet owners and two named scanner owners, never copied or
aggregated. Keep the active generation while scanning and installing a complete
candidate. Watch exact opened descriptors, verify all parent/name/identity
bindings and current included membership, then drain namespace events to true
idle before promotion. Drain budget exhaustion is distinct from idle: existing
`changes()==0` cannot establish stability after its 256-record cap.

Each attempt has a combined 4096-record queue budget; namespace changes,
overflow, unexpected terminal events, verification differences and exhausted
budgets invalidate the attempt. Reconcile at most eight times, then stop with
an explicit incomplete-coverage error. Open descriptors prevent identity reuse
while retained. Close a retired WatchSet before closing its directory anchors.
Both generations together can hold up to 512 directory anchors and two inotify
instances; transient traversal descriptors must also have a measured bound.

A successful reconciliation always requests a full selected command. This repairs
current-state command coverage, not notification history or an atomic snapshot.
Changes before installation may have no surviving event; the full command still
runs after complete coverage is re-established.

## Child and debounce integration

During an active child, latch coverage-dirty state and continue cooperative
supervision/reaping. Once the old set is terminal, stop reading it, but continue
signal handling and bounded explicit-root identity/link checks. Reconcile only
after child cleanup, then schedule an immediate full command. No new child or
cache lock is held during discovery/reconciliation. Cancellation and failed
coverage restoration use existing cleanup and code125 behavior. Debounce never
postpones coverage repair or event-loss recovery.

Counts bound work, not wall-clock filesystem lookup time. Check cancellation
between bounded native scan/install/drain phases. A continuously changing tree
can exhaust reconciliation and stop conservatively.

## Required race and lifecycle evidence

- Exact descriptor identity across path replacement and symlink swaps.
- Root deletion while its anchor remains open, including terminal old sets.
- New populated subtrees and removals/moves across exclusion boundaries.
- Namespace changes behind more than256 irrelevant buffered records.
- Partial registration failure, entry/depth/directory/drain/retry exhaustion.
- Cancellation during discovery and repair, and delayed active-child cleanup.
- Independent generations, fd leaks, CLOEXEC, original explicit/default behavior.
- Independent design/security/implementation reviews and complete qualification.

Two independent design reviews identified the path-binding race, held-fd deletion
delay and false-idle drain hazard. The descriptor primitive and sentinel protocol
address those findings; production adoption remains gated on executable evidence.

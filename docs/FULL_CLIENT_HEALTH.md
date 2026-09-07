# Read-only operational health

`scripts/full_client_health.py --config PRIVATE_CONFIG` performs bounded Linux
probes. It does not start a service, acquire a world lock, reset a database or
submit a model request. A successful probe is an operational snapshot; source
freezing, trial authorization and publication remain separate checks.

Schema 1 retains the leased integration-preview contract. It may explicitly set
`mode: "leased-preview"`. Schema 2 requires `mode: "normal-worker"`; it never
reinterprets the old world's expired lease as the current worker's lease.

## Normal-worker configuration

Keep host paths and identities in private runtime configuration outside Git.
Schema 2 accepts these fields:

| Field | Required evidence |
| --- | --- |
| `schema_version`, `mode` | Exactly `2`, `normal-worker` |
| `services` | Four distinct existing units keyed `world`, `worker`, `web`, `cosmic` |
| `processes` | Exact `executable`, `argv`, numeric `uid` and `working_directory` for worker, web and Cosmic |
| `world_lock`, `queue_lock` | Existing canonical regular files; distinct device/inode identities |
| `queue_database` | Existing canonical queue SQLite database, queried read-only with `query_only` enabled |
| `admin_socket` | Web-owned mode-0600 Unix socket in a web-owned mode-0700 directory |
| `game_ports` | Native listeners whose socket inodes belong to the verified Cosmic PID |
| `base_url` | Numeric loopback HTTP URL; its listening socket must belong to the verified web PID |
| `min_available_mib` | Optional minimum available host memory, default 1,024 MiB |

The old world helper must be stopped, with PID zero. Worker, web and Cosmic must
be running under stable systemd invocation IDs and process start ticks. Both
existing exclusive kernel flock entries must belong only to the worker. The
queue must contain no queued, running or rendering attempts. Process, lock and
queue observations are rechecked during the probe window.

The private status socket authenticates the web process with kernel peer
credentials. The public loopback request disables ambient proxies and redirects;
its run identity/state must agree with the private response. Ready requires
explicitly inactive controller/worker work, no retained execution lease, no
pending browser release or quarantined run, and settled idle capture. The bridge
now reports those booleans truthfully even before its first run.

`healthy_waiting` means the existing browser is freshly polling its waiting
page. It does not require gameplay frames. `healthy_rendering` additionally
requires a fresh post-render observation. Status transport and probe time count
against freshness; a delayed response cannot preserve an old fresh boolean.
A static character alone establishes neither condition.

The normal probe has a 25-second deadline, bounded command/status/table reads
and a 4,096-descriptor enumeration limit. Failures return safe codes rather than
raw subprocess output or configuration contents. `durable-trial` is explicitly
unsupported here: use the trusted runner/backend context for that mode, because
relay status cannot establish database account state or runner lock ancestry.

Offline tests exercise actual synthetic SQLite/files/socket ownership parsing,
injected process replacement, retained leases, stale rendering and delayed
status. They do not establish acceptance on a deployed service revision.

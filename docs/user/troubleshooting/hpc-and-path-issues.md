# HPC and Path Issues

Many scripts in this repository intentionally assume a specific local and remote layout. Most path-related failures happen when only one call site is updated or when the environment differs from the original machine.

## Common path assumptions

- local repo root: `/home/clivewong/proj/longevity`
- remote HPC root: `/home/clivewong/proj/long`
- local preprocessing output: `fmriprep/`
- analysis output: `results/`

## Before changing paths

1. Search the connected workflow scripts, not just one file.
2. Check both script entrypoints and app defaults.
3. Re-run a narrow smoke test before a large batch.

## SSH and rsync failures

- Confirm SSH access first.
- Confirm the remote base directory exists.
- Confirm `rsync` is available locally.
- Re-run a single manual subcommand such as `upload` or `status` before restarting the full batch.

## SSH rate limits and port tunnels

If direct SSH to the HPC is rate-limited, create a local tunnel:

```bash
ssh -L 2222:<hpc-host>:22 <gateway-host>   # or simply:
ssh -p 2222 localhost                       # if tunnel already established
```

Then configure the app so all SSH and rsync traffic goes through the tunnel:

| Setting | Value |
|---|---|
| **Settings → HPC → Host** | `localhost` |
| **Settings → HPC → Port** | `2222` |

The `hpc.port` config key is passed directly to `paramiko.SSHClient.connect()` and to the `-e "ssh -p PORT"` flag in all `rsync` calls.

## App config path handling

The app configuration supports both `${var}` substitution and `~` expansion. Prefer updating config values rather than hardcoding fully expanded paths into docs or settings.

## Remote cleanup surprises

`batch_fmriprep.sh` treats remote cleanup as part of normal operation. If you need to inspect remote outputs before they are removed, do that before the cleanup step or use the manual subcommands.

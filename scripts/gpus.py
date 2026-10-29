"""`make gpus`: GPU memory per service, from nvidia-smi, each process named by its systemd
unit (ps -o unit, or uunit for user units) or, failing that, its command. Standard library only."""

from __future__ import annotations

import subprocess


def run(*cmd: str) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


def main() -> None:
    uuid_to_index = dict(
        reversed(line.split(", ")) for line in
        run("nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader").splitlines())
    rows = []
    for line in run("nvidia-smi", "--query-compute-apps=gpu_uuid,pid,used_memory,process_name",
                    "--format=csv,noheader,nounits").splitlines():
        uuid, pid, mib, path = line.split(", ", 3)
        unit = run("ps", "-o", "unit=", "-p", pid)
        if unit.startswith("user@"):  # a systemd user unit: name it, not the user manager
            unit = run("ps", "-o", "uunit=", "-p", pid)
        # ps cannot always see the process nvidia-smi lists; then show its executable.
        name = unit if unit.endswith(".service") else run("ps", "-o", "comm=", "-p", pid) or path
        rows.append((int(uuid_to_index.get(uuid, -1)), name, int(mib)))
    totals: dict[int, int] = {}
    print(f"{'GPU':>3}  {'MiB':>7}  service")
    for gpu, name, mib in sorted(rows):
        totals[gpu] = totals.get(gpu, 0) + mib
        print(f"{gpu:>3}  {mib:>7,}  {name}")
    for gpu, mib in sorted(totals.items()):
        print(f"GPU {gpu} total {mib:,} MiB")


if __name__ == "__main__":
    main()

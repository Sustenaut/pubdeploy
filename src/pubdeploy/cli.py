"""pubdeploy: what a service needs before it deploys, whether it has it,
and making it; and the checks a deploy to Kubernetes runs.

    pubdeploy walk [--fulfil] [--yes] [--unit NAME] [--kubectl CMD] [--server HOST]
                   [--zones PATH] [--journal URL] [--json] [--offline] [--namespace NS]
                   [--tolerate-unknown]
    pubdeploy check ...                  walk without --fulfil
    pubdeploy types                      every need type, and its keys
    pubdeploy k8s preflight|diagnose     before an apply, and after a failed rollout
    pubdeploy sync-check [--check]       what `pubkit sync` runs of pubdeploy's
    pubdeploy bump                       what `pubkit bump` runs of pubdeploy's

A repository runs its pinned pubdeploy as ./pubdeploy, which `pubkit sync`
writes beside ./pubkit where pubkit.json has a deploy block, with each
deploy.providers wheel, so the need types other packages offer (pubsec's,
pg-backup's) load. It runs in the repository's root.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def main(argv: list[str] | None = None) -> int:
    given = sys.argv[1:] if argv is None else argv
    if given[:1] == ["k8s"]:
        # Its own parser, in a file a server can run without the rest.
        from .k8s import main as k8s  # noqa: PLC0415
        return k8s(given[1:])
    parser = argparse.ArgumentParser(prog="pubdeploy", description=__doc__.split("\n")[0])
    parser.add_argument("--version", action="version", version=f"pubdeploy {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    for verb, said in (("walk", "check every need, in order, print each one's state, and with --fulfil make "
                                "what is missing; exit 1 when one is not ready"),
                       ("check", "walk without --fulfil: check every need, changing nothing")):
        p = commands.add_parser(verb, help=said)
        if verb == "walk":
            p.add_argument("--fulfil", action="store_true",
                           help="after the checks, make each auto need that is missing, once the plan is confirmed")
            p.add_argument("--yes", action="store_true", help="confirm the plan without asking (no write token "
                                                              "is asked for without a terminal)")
        p.add_argument("--tolerate-unknown", action="store_true",
                       help="exit 0 unless a need is missing, drift or blocked: an unknown one fails nothing")
        p.add_argument("--unit", metavar="NAME", help="walk one unit of the deploy block; every unit by default")
        p.add_argument("--offline", action="store_true",
                       help="check only what needs no network: the manifests against the needs, and the files")
        p.add_argument("--json", action="store_true", help="print the walk as a deploy-journal/2 document")
        p.add_argument("--kubectl", metavar="CMD",
                       help="the kubectl command, such as 'k3s kubectl --kubeconfig FILE', or the server's "
                            "read-only verb, 'ssh -i KEY deploy@HOST {unit} kubectl-read'")
        p.add_argument("--server", metavar="HOST", help="the admin channel: kubectl and commands over ssh root@HOST "
                                                         "(default SUSTENAUT_SERVER, without --kubectl)")
        p.add_argument("--zones", type=Path, metavar="PATH",
                       help="the pubkit.json, here or in a checkout beside this one, whose hosting block "
                            "keeps the zone of the deploy's host")
        p.add_argument("--journal", metavar="URL", help="also write the journal to storage (or PUBKIT_JOURNAL_URL)")
        p.add_argument("--namespace", metavar="NS", help="another namespace than the unit's")
    commands.add_parser("types", help="every need type pubdeploy and the installed packages offer, and its keys")
    commands.add_parser("k8s", help="check the Secrets rendered manifests read before a deploy, or show "
                                    "why a rollout failed (pubdeploy k8s --help)")
    p = commands.add_parser("sync-check", help="the deploy block's offline check, and the scheduled walk's "
                                               "caller seeded: what pubkit sync runs")
    p.add_argument("--check", action="store_true", help="change nothing: fail where sync would seed")
    commands.add_parser("bump", help="move deploy.providers and the uses of pubdeploy's workflows to the "
                                     "latest releases: what pubkit bump runs")
    args = parser.parse_args(given)
    root = Path.cwd()
    if args.command == "types":
        from . import run_types  # noqa: PLC0415
        return run_types()
    if args.command == "sync-check":
        from .config import read_config  # noqa: PLC0415
        from .hooks import check  # noqa: PLC0415
        lines, failed = check(root, read_config(root), args.check)
        for line in lines:
            print(line, file=sys.stderr if line.startswith("pubdeploy:") else sys.stdout)
        return 1 if failed else 0
    if args.command == "bump":
        from .hooks import bump  # noqa: PLC0415
        for line in bump(root):
            print(line)
        return 0
    from . import run_walk  # noqa: PLC0415
    from .config import confined  # noqa: PLC0415
    # --zones is another repository's pubkit.json, so it may be in a
    # checkout beside this one: a pubkit.json in the parent directory's tree.
    zones = confined(args.zones, "the --zones file", also=(root.parent,)) if args.zones else None
    if zones is not None and zones.name != "pubkit.json":
        sys.exit(f"pubdeploy: the --zones file ({args.zones}) must be a repository's pubkit.json")
    return run_walk(root, args.offline, args.json, args.kubectl, zones, args.namespace,
                    fulfil=getattr(args, "fulfil", False), unit=args.unit, server=args.server,
                    yes=getattr(args, "yes", False), journal_url=args.journal,
                    tolerate_unknown=args.tolerate_unknown)


if __name__ == "__main__":
    sys.exit(main())

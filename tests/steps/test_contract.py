"""The provider contract (pubdeploy.contract), the README's list of it, and
the stand-in provider this suite walks with, which keeps to it."""

from __future__ import annotations

import ast
import re
from dataclasses import fields
from pathlib import Path

import standin_provider
from pytest_bdd import parsers, scenarios, when

from pubdeploy import contract

scenarios("contract.feature")

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"


@when("the contract's Context names the walk's Context lacks are gathered")
def context_lacks(ctx):
    from pubdeploy.model import Context  # noqa: PLC0415
    ctx.attempt(lambda: sorted(contract.CONTEXT - {f.name for f in fields(Context)}))


@when("the contract's need and result names the walk's Need and Result lack are gathered")
def need_result_lack(ctx):
    need = contract.Need("example.thing", "one", {})
    result = contract.Result("ready", "there")
    ctx.attempt(lambda: sorted([n for n in contract.NEED if not hasattr(need, n)]
                               + [n for n in contract.RESULT | contract.RESULT_OPTIONAL if not hasattr(result, n)]))


def listed(section: str, lead: str) -> set[str]:
    """The backquoted names of the README sentence that starts `lead`, up to its full stop; a call's name alone."""
    start = section.index(lead)
    sentence = section[start:section.index(". ", start)]
    return {re.split(r"[(]", name)[0] for name in re.findall(r"`([^`]+)`", sentence)}


@when(parsers.parse('the names README\'s "Provider contract" lists, and the contract\'s, are compared'))
def readme_compared(ctx):
    def compared():
        text = (ROOT / "README.md").read_text()
        section = text[text.index("### Provider contract"):]
        section = " ".join(section[:section.index("\n### ", 5) if "\n### " in section[5:] else None].split())
        said = {"Context": listed(section, "Context: "), "Result": listed(section, "Result: "),
                "Need": listed(section, "Need: "), "Type": listed(section, "Type: ")}
        wanted = {"Context": contract.CONTEXT, "Result": contract.RESULT | contract.RESULT_OPTIONAL,
                  "Need": contract.NEED, "Type": contract.TYPE | contract.TYPE_OPTIONAL}
        out = []
        for what, names in wanted.items():
            got = said[what]
            out += [f"{what}: README lacks {n}" for n in sorted(names - got)]
            out += [f"{what}: README has {n}, the contract does not" for n in sorted(got - names)]
        return out
    ctx.attempt(compared)


@when("the modules of pubdeploy that pubdeploy.contract imports are gathered")
def contract_imports(ctx):
    def gathered():
        tree = ast.parse((ROOT / "src" / "pubdeploy" / "contract.py").read_text())
        return sorted({f"pubdeploy.{node.module}" if node.level else node.module
                       for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                       if node.level or (node.module or "").startswith("pubdeploy")})
    ctx.attempt(lambda: str(gathered()))


@when("the stand-in's types are checked by the contract")
def standin_checked(ctx):
    def checked():
        needs, _hooks = standin_provider.points()
        return [f"{p.name}: {why}" for p in needs for why in contract.problems(p.load())]
    ctx.attempt(checked)


@when("the names the stand-in reads from a Context, and not in the contract, are gathered")
def standin_reads(ctx):
    source = Path(standin_provider.__file__).read_text()
    ctx.attempt(lambda: sorted(set(re.findall(r"\bctx\.([a-z_]+)", source)) - contract.CONTEXT))


@when("the stand-in's hook is checked by the contract")
def standin_hook(ctx):
    _needs, hooks = standin_provider.points()
    ctx.attempt(lambda: [why for h in hooks for why in contract.hook_problems(h.load())])


HOOKS = {"takes two arguments": lambda ctx, plan: None, "is not a function": "prepare"}


@when(parsers.parse("a hook that {kind} is checked by the contract"))
def bad_hook(ctx, kind):
    ctx.attempt(lambda: str(contract.hook_problems(HOOKS[kind])))


@when("this suite's imports of pubsec are gathered")
def no_pubsec(ctx):
    ctx.attempt(lambda: [f"{path.relative_to(TESTS)}: {line.strip()}" for path in sorted(TESTS.rglob("*.py"))
                         for line in path.read_text().splitlines() if re.match(r"\s*(from|import)\s+pubsec\b", line)])

"""Check the translation catalogs (airemove/locales/<code>.json) against the texts in the code.

The texts are the string literals given to _(), _n() and N_() in airemove/, installer/ and mcp/ (see
airemove/i18n.py). For each catalog it reports:
  missing      texts with no translation yet (the app shows them in English)
  unused       catalog entries no text in the code uses any more
  placeholder  translations whose {fields} differ from the English text's
It also flags functions that call _() but use `_` as a variable too (that would shadow the function).

  python tools/i18n_check.py            report; exit status 1 when anything needs attention
  python tools/i18n_check.py --update   also add the missing texts to every catalog (empty: to translate) and drop
                                        the unused ones
Standard library only.
"""
import ast
import json
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ["airemove", "installer", "mcp"]
LOCALES = ROOT / "airemove" / "locales"
MARKERS = {"_": 1, "N_": 1, "_n": 2}  # function: how many leading arguments are texts


def texts():
    """{text: [where]} and the shadowing problems."""
    found, shadow = {}, []
    for d in SOURCES:
        for f in sorted((ROOT / d).rglob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"), str(f))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in MARKERS:
                    for arg in node.args[:MARKERS[node.func.id]]:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            found.setdefault(arg.value, []).append(f"{f.relative_to(ROOT)}:{node.lineno}")
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    calls = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("_", "_n")
                                for n in ast.walk(node))
                    binds = [n for n in ast.walk(node) if isinstance(n, ast.Name) and n.id == "_"
                             and isinstance(n.ctx, ast.Store)]
                    args = [a for a in node.args.args + node.args.kwonlyargs if a.arg == "_"]
                    if calls and (binds or args):
                        shadow.append(f"{f.relative_to(ROOT)}:{node.lineno} {node.name}() binds `_`")
    return found, shadow


def fields(text):
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name}


def main():
    update = "--update" in sys.argv
    found, shadow = texts()
    bad = bool(shadow)
    for s in shadow:
        print("SHADOW", s)
    for cat in sorted(LOCALES.glob("*.json")):
        data = json.loads(cat.read_text(encoding="utf-8"))
        meta = {k: v for k, v in data.items() if k.startswith("@")}
        entries = {k: v for k, v in data.items() if not k.startswith("@")}
        missing = [t for t in found if not entries.get(t)]
        unused = [t for t in entries if t not in found]
        placeholder = [t for t, v in entries.items() if v and t in found and fields(t) != fields(v)]
        print(f"{cat.name}: {len(found)} texts, {len(found) - len(missing)} translated, {len(missing)} missing, "
              f"{len(unused)} unused, {len(placeholder)} with wrong placeholders")
        for t in missing:
            print("  missing     ", json.dumps(t, ensure_ascii=False)[:110], " <-", found[t][0])
        for t in unused:
            print("  unused      ", json.dumps(t, ensure_ascii=False)[:110])
        for t in placeholder:
            print("  placeholder ", json.dumps(t, ensure_ascii=False)[:110])
        bad = bad or bool(missing or unused or placeholder)
        if update:
            out = dict(meta)
            for t in sorted(found, key=str.lower):
                out[t] = entries.get(t, "")
            cat.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"  {cat.name} updated")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

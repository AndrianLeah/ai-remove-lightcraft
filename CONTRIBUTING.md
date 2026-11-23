# Contributing

Thanks for looking. AI Remove is a small project with one maintainer, and an unofficial plug-in: it is not made,
sponsored or endorsed by the ArtCraft team, who make LightCraft, nor by Chromaforge's contributors.

## What helps most

- **Reports from real graphics cards.** CI runs only LaMa, with stand-ins for the large models, so it never sees how
  they use a card's memory; several reports so far were memory running out on 8 GB cards. An issue with the output
  of `airemove-cli --check` and the end of the log is usually enough to fix one: the issue form says where to find
  both.
- **AI Remove in your language.** A language is one file: the README's [Languages](README.md#languages) says how to add
  it.
- **Ideas** go in [Discussions](https://github.com/AndrianLeah/ai-remove-lightcraft/discussions), so others can add
  to them.

## Running it from source

AI Remove runs with the Python of an install, which has PyTorch and the models. Install it once (README,
[Install](README.md#install)), then from a clone:

```sh
~/AIRemove/venv/bin/python airemove/airemove.py --check
```

On Windows the Python is `%USERPROFILE%\AIRemove\venv\Scripts\python.exe`. The README's
[Development](README.md#development) says what each folder holds and how the release packages are built.

## Checking a change

What CI's first job runs, with Python 3 and no install:

```sh
git ls-files -z '*.py' | xargs -0 python3 -m py_compile
python3 tools/i18n_check.py
python3 tools/ci_settings.py
shellcheck installer/bootstrap.sh mcp/run_mcp.sh "Install on Mac.command" "Install on Linux.sh"
```

Then CI installs AI Remove for real on Windows, macOS and Linux and runs removals end to end, with each kind of
picture and with stand-ins for the large models (the `tools/ci_*.py` scripts; [`ci.yml`](.github/workflows/ci.yml) says
what each one checks). They make their own synthetic photos, so no photo or token is needed. A pull request has to pass
them.

## Pull requests

Keep them small and about one thing, and say what you tested, on which system and graphics card.

Text the app shows is written as `_("…")` and needs its Italian line in
[`airemove/locales/it.json`](airemove/locales/it.json): `python3 tools/i18n_check.py --update` adds the new texts for
you to translate, and CI checks that none is missing.

A change in what AI Remove does goes into both [README.md](README.md) and [README.it.md](README.it.md).

For a security problem, don't open an issue: see [SECURITY.md](SECURITY.md).

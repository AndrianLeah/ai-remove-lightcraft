# Security

AI Remove runs on your computer, installs Python packages and model weights, and drives LightCraft and Chromaforge
through their local control channels, so a flaw in it matters. What it sends over the network, and who can use those
channels, is in the README's [Privacy and security](README.md#privacy-and-security).

## Reporting a problem

Please don't open a public issue for something that could put people who use AI Remove at risk. Use **Report a
vulnerability** on the repository's [Security tab](https://github.com/AndrianLeah/ai-remove-lightcraft/security/advisories/new)
instead: it reaches the maintainer privately. Say which version (at the top of AI Remove's window, or `version` in
`airemove-cli --check`) and system you are on, and how to reproduce it.

Only the latest release is supported: a fix goes into a new release.

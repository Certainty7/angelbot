# Security policy

## Reporting a vulnerability

Do not open a public issue. Use GitHub's private vulnerability reporting on this repository
(**Security** tab, then **Report a vulnerability**). If the button is not available, open an issue
that says only that you have a security report, with no details, and the maintainer will open a
private channel.

Please include the affected command or code path, a reproduction if you have one, and the version
or commit you tested.

## In scope

- Bypassing the owner or permission checks, including through the natural-language router or a
  model-emitted control tag.
- Reading data outside the channels a member can see, or reading a direct message through the
  archive.
- Leaking a token, key or database file through the repository, logs or a reply.
- Command injection or a path escape in media download, cleanup or the subprocess runner.

## Owner-only commands

A small set of commands is gated by a private owner id configured outside the repository, not by
a Discord permission: `/sovereign` (including its role and moderation modes), `/dm_logs`, `/dm_send`,
`/whisper`, `/harem`, `/autonomy`, `/silence`, `/mood`, `/sync` and `/diagnostics`. They are listed with
their parameters in `docs/COMMANDS.md`. The bot also forwards a DM sent to it to the owner and keeps
those DMs for 30 days, as stated in `docs/MEMORY.md` and on the site's privacy page. None of this
surface is reachable by a guild member, and nothing about it is hidden from the owner or the host.

## Out of scope

- Spam or abuse from a bot token or account that is already compromised.
- Rate limits, model output quality and moderation decisions made by a server's own staff.
- Denial of service from a self-hosted deployment the maintainer does not control.

## Supported versions

The `master` branch is the supported version. There are no maintained release branches.

## Response

This is a single-maintainer project. Reports are acknowledged when they are read, and a fix lands
on `master` when it is ready. Please give the maintainer time to ship a fix before writing about
the issue publicly.

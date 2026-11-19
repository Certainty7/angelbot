# Command reference

Angel registers 65 commands at startup: 62 slash commands and 3 message context menus. The music cog adds 4 more when it is enabled.

Parameters use `<required>` and `[optional]` notation. The permission column is the Discord permission the command needs by default; the owner ID bypasses these checks. Command descriptions are Arabic inside Discord.

Eleven commands also refuse everyone but the owner at runtime: `/sync`, `/diagnostics`, `/mood`, `/autonomy`, `/silence`, `/harem`, `/sovereign`, `/dm_send`, `/whisper`, `/dm_logs` and `/cleanup` (global storage sweep). Their row still shows the Discord permission the command carries.

## Moderation (17)

| Command | Parameters | Permission |
|---|---|---|
| `/add_role` | <member>, <role> | `manage_roles` |
| `/announce` | <channel>, <title>, <message>, [ping_everyone] | `manage_guild` |
| `/ban` | <member>, [reason], [delete_days] | `ban_members` |
| `/clear_warnings` | <member> | `moderate_members` |
| `/kick` | <member>, [reason] | `kick_members` |
| `/lock` | [channel], [reason] | `manage_channels` |
| `/purge` | <amount>, [member] | `manage_messages` |
| `/remove_role` | <member>, <role> | `manage_roles` |
| `/set_modlog` | [channel] | `administrator` |
| `/slowmode` | <seconds> | `manage_channels` |
| `/sync` |  | `administrator` |
| `/timeout` | <member>, <minutes>, [reason] | `moderate_members` |
| `/unban` | <user_id>, [reason] | `ban_members` |
| `/unlock` | [channel] | `manage_channels` |
| `/untimeout` | <member> | `moderate_members` |
| `/warn` | <member>, <reason> | `moderate_members` |
| `/warnings` | <member> | `moderate_members` |

## Community (11)

| Command | Parameters | Permission |
|---|---|---|
| `/afk` | [reason] | none |
| `/auto_reply` | <action>, [trigger], [response] | `manage_guild` |
| `/avatar` | [member] | none |
| `/editsnipe` |  | none |
| `/giveaway` | <minutes>, <winners>, <prize> | `manage_guild` |
| `/ping` |  | none |
| `/poll` | <question>, <option1>, <option2>, [option3], [option4] | none |
| `/serverinfo` |  | none |
| `/snipe` |  | none |
| `/ticket_panel` | [title], [description] | `manage_channels` |
| `/userinfo` | [member] | none |

## Memory (6)

| Command | Parameters | Permission |
|---|---|---|
| `/admin_note` | <topic>, <content> | none |
| `/budget` |  | none |
| `/clear_history` |  | none |
| `/data` | [action], [confirm] | none (self-service) |
| `/memory` | [action], [text], [style] | none |
| `/mood` | <value> | none |
| `/rules` | <question> | none |

## Chat (4)

| Command | Parameters | Permission |
|---|---|---|
| `/chat` | <message>, [image] | none |
| `/imagine` | <prompt>, [style] | none |
| `/summarize_channel` | [limit], [question] | none |
| `/translate` | <text>, <target_language> | none |

## Media (2)

| Command | Parameters | Permission |
|---|---|---|
| `/cleanup` |  | `manage_guild` |
| `/fix` | <url> | none |

## Fun and XP (4)

| Command | Parameters | Permission |
|---|---|---|
| `/gif` | <action>, [target] | none |
| `/leaderboard` |  | none |
| `/lore` |  | none |
| `/rank` | [member] | none |

## Control (3)

| Command | Parameters | Permission |
|---|---|---|
| `/autonomy` | [mode] | none |
| `/help` |  | none |
| `/silence` | <mode>, [channel] | none |

## Owner (6)

| Command | Parameters | Permission |
|---|---|---|
| `/custom_action` | <mode>, [phrase], [action_type], [value], [custom_reply] | `administrator` |
| `/dm_logs` | [limit] | `administrator` |
| `/dm_send` | <message>, [user], [user_id] | `administrator` |
| `/harem` | <action>, [member], [user_id], [title] | `administrator` |
| `/sovereign` | <action>, [target_member], [role], [text] | `administrator` |
| `/whisper` | <message> | `administrator` |

## Flagship (6)

| Command | Parameters | Permission |
|---|---|---|
| `/angel` |  | none |
| `/diagnostics` |  | `administrator` |
| `/guard` | <mode> | `manage_guild` |
| `/knowledge` | <action>, [topic], [content], [entry_id] | `manage_guild` |
| `/pulse` |  | `manage_guild` |
| `/rep` | <member> | none |

## Productivity (2)

| Command | Parameters | Permission |
|---|---|---|
| `/autorole` | [role] | `manage_roles` |
| `/sticky` | <mode>, [message] | `manage_messages` |

## Context menus (3)

| Command | Applies to |
|---|---|
| تلخيص الرسالة | Message |
| ترجمة وتحليل | Message |
| اقتراح رد ومهام | Message |

## Music (4, lazy)

Registered only when the music cog is enabled (`MUSIC_ENABLED`, default on).

| Command | Parameters | Permission |
|---|---|---|
| `/play` | <query> | none (use in a voice channel) |
| `/skip` |  | none (use in a voice channel) |
| `/queue` |  | none (use in a voice channel) |
| `/playlist` | <action>, [name], [query] | none (use in a voice channel) |

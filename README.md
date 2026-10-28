# Mantella Living World - World

What's happening and what you've done, told to [Mantella](https://www.nexusmods.com/skyrimspecialedition/mods/98631) NPCs. A module of [Mantella Living World - Integration Hub](https://github.com/Abhisek571/Mantella-Living-World-Hub).

| Feature | What happens |
|---|---|
| World state | `SKSE/Plugins/StorageUtilData/MantellaLivingWorld/world.json`: fame and bounty per hold, war side, Thane titles, guild ranks, main quest stage, dated quest outcomes. Refreshed when a conversation starts and on location changes (at most every 30 s) |
| Quest outcomes | `quest_outcomes.json`: main quest, Civil War, Companions, College, Thieves Guild, Dark Brotherhood, Thane titles, Riverwood and Whiterun side quests; each with who would know |
| Since we last met | An NPC you meet on a later day hears what changed: new Thane titles, war side, bounty, fame |
| Hiding | Sneaking unseen, or a hood in a hold where you are not famous: the NPC does not recognise you (uncanny observers do) |
| Who knows whom | In group talks, one line per pair: strangers, know of, acquainted, close |
| SettleCrime | Guards, stewards and Jarls settle a non-violent bounty: pay, bribe (Speech lowers the price) or persuade (100 gold or less, once a day per hold). Thanes get minor bounties waived. Violent crime gold is never cleared |
| ReportCrime | Guards add a bounty only when a witness in the conversation told them |

Turn off Mantella's own AbsolveCrime and ReportCrime actions.

Requires: [Mantella Living World - Integration Hub](https://github.com/Abhisek571/Mantella-Living-World-Hub), [Mantella](https://www.nexusmods.com/skyrimspecialedition/mods/98631) 0.14, [PapyrusUtil](https://www.nexusmods.com/skyrimspecialedition/mods/13048), [Address Library for SKSE Plugins](https://www.nexusmods.com/skyrimspecialedition/mods/32444) (for its SKSE plugin).

Data: `py -3 tools/build_quest_outcomes.py` rebuilds `quest_outcomes.json` (reads Quest Journal Overhaul's quest files for holds); `py -3 tools/test_build_quest_outcomes.py` runs its tests. `py -3 tools/make_records.py` writes the plugin YAML and action files.

Built with the hub's `tools/build.py`. License: GNU AGPL-3.0.

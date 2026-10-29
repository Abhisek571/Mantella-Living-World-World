# Mantella Living World - World

What's happening in Skyrim and what you've done, told to Mantella NPCs. A module of [Mantella Living World - Integration Hub](https://github.com/Abhisek571/Mantella-Living-World-Hub).

| Feature | What it does |
|---|---|
| What NPCs know about you | Each NPC is told what they would know: your fame in their hold, your bounty (guards always; everyone in the hold once it is 1000 gold or more), Thane titles and quest outcomes whose word reached them (their hold, their guild or side, or people named in it). One short block, the same for the whole talk. Switch it off with "Tell NPCs what they would know about you" in the Hub MCM. With Mantella Living World - Knowledge installed, Dragonborn news is left to Knowledge |
| Quest outcomes | Main quest, Civil War, Companions, College, Thieves Guild, Dark Brotherhood, Thane titles and Riverwood and Whiterun side quests, each told only to NPCs who would know |
| Since we last met | An NPC you meet on a later day hears what changed since last time: new titles, war side, bounty, fame. At most 3 items, bounty and fame only when in the same hold as last time. Events from before you installed are not announced |
| Hiding | Sneaking unseen, or a hood, helmet or mask in a hold where you are not famous: the NPC does not recognise you. Friends, followers and teammates always do, and uncanny observers see through it. Outside any hold you count as not famous |
| Who knows whom | In group talks, one line per pair: strangers, know of, acquainted, close |
| Party banter | Party members (followers set as teammates, for example with NFF) react to a voiced line nearby, to you entering an inn and to the end of a fight you were hit in. Needs a party member and the Hub's pacing limits apply (banter every 2 minutes at most). A banter talk ends after 45 seconds |
| Initiative | An NPC with a reason walks up to you and starts a talk. This needs another module that gives NPCs a reason, such as Mantella Living World - Missives. Wait 10 minutes between approaches. Switch it off with "Come over to talk" |
| SettleCrime | Guards settle a non-violent bounty: pay (asks you Yes/No first), bribe (1.5 times the bounty, down to 1 times with Speech 100; you keep the stolen goods) or persuade (100 gold or less, once a day per hold). Thanes and well-known players (fame 5 or more) get a bounty of 40 gold or less waived. Violent crime is never cleared. Bribe and persuade need Mantella's Advanced Actions on; without it a guard can only take payment |
| ReportCrime | Guards add a bounty only when another NPC is present in the talk as a witness. Needs Advanced Actions on (it picks the crime) |

Turn off Mantella's own AbsolveCrime and ReportCrime actions (both are off by default).

Requires:
- Mantella Living World - Integration Hub
- [Mantella](https://www.nexusmods.com/skyrimspecialedition/mods/98631) 0.14 with [Mantella - Direct AI Connect](https://github.com/Abhisek571/Mantella-Anthropic-API), which the Hub extension and guard-only actions need
- Advanced Actions on in Mantella (Actions tab of its settings) for bribe, persuade and ReportCrime
- SKSE and [PapyrusUtil SE](https://www.nexusmods.com/skyrimspecialedition/mods/13048)
- [Papyrus MessageBox - SKSE NG](https://www.nexusmods.com/skyrimspecialedition/mods/83578)
- [Address Library for SKSE Plugins](https://www.nexusmods.com/skyrimspecialedition/mods/32444)

Optional:
- A follower framework that sets party members as teammates (NFF or vanilla followers) for banter
- Mantella Living World - Missives (or another module that gives NPCs a reason) for initiative
- Mantella Living World - Knowledge for Dragonborn news and quest state

Build: the Hub's `tools/build.py --only world` (the SKSE plugin first, with `plugin/build.ps1`). Data: `py -3 tools/build_quest_outcomes.py` (reads Quest Journal Overhaul's quest files for holds, only needed to rebuild the data), tests in `tools/test_build_quest_outcomes.py`; `py -3 tools/make_records.py` writes the plugin YAML and action files.

License: GNU AGPL-3.0 for the scripts and data; the SKSE plugin in `plugin/` is GPL-3.0.

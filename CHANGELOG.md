# Changelog

Every change to Mantella Living World - World. The Nexus page lists only the main changes for each version.

## 1.2.0 (2026-11-09)

### New
- Bribes and persuasion: settle a bounty with a guard by paying them off or talking them round (persuading needs Speech at least the bounty).
- Recognition: NPCs who have seen your face remember it, and your fame in the hold and Thane titles count.
- Meetings, NPCs taking the first word, and banter between party members improved.

### Fixed
- Theft and pickpocket reports removed; murder reports kept.
- A later murder elsewhere hid an earlier murder from that hold's guards; each hold now keeps its own.
- Gold counts are net per container, trades count both ways, counts never go below zero, and followers are left out.
- The event log is cleared when you load a save, and the event list is capped.

## 1.1.3 (2026-11-04)
- Opening a merchant's shop no longer crashes when the game's default Gold entry is empty.

## 1.1.2 (2026-11-04)
- The SKSE plugin is now also built for Skyrim VR; the older build stopped the game launching there.
- Party banter no longer uses the scan that crashes in VR.
- Now requires powerofthree's Papyrus Extender and Integration Hub 1.1.7. Skyrim VR also needs the VR Address Library.

## 1.1.1 (2026-11-01)
- Fixes "MLWW_Listener.dll: disabled, fatal error occurred while loading plugin": the plugin no longer needs the Visual C++ runtime installed, and a log file that can't be opened (for example a Documents path with non-English letters) no longer stops it loading.

## 1.1.0 (2026-10-30)
- New: what you did to each NPC, told to them when they join a talk: caught stealing from them or picking their pocket, wearing something stolen from them, waking them up, striking them, your gifts (gold included), trade with them today, and a merchant short of coin after buying from you.
- Deaths are recorded so Relationships can grieve.

## 1.0.0 (2026-10-30)
- First release. Requires Mantella Living World - Integration Hub.

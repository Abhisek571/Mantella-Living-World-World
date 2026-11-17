# Changelog

Every change to Mantella Living World - World. The Nexus page lists only the main changes for each version.

## Unreleased

### New
- Ordinary dialogue with an NPC (the topics you pick in the game's dialogue menu and their answers, from any mod) is kept from the moment the game loads, also before Mantella's first conversation, so that NPC's next talk knows it. Nothing expires: the lines wait (with the day, the place and the mod they come from) until that NPC's next talk turns them into memories, however much later. Up to 60 exchanges per NPC and 200 NPCs; when an NPC's store is full, a base game line goes first. Needs the Integration Hub.
- Fights: every NPC who fought near you is told what really happened from their side (who fought, who died, how hurt each was, how much each did, close calls, rescues, magic and kills), during the fight and for 6 game hours after. A fight worth remembering is added to their memory. Drain or slow magic counts as yours only when you really cast a spell with that effect a few seconds before; an aura, ability, enchantment or perk you carry never does. Settings on the Hub MCM's World page: on/off, include bystanders, hours to keep.
- Trading by talk: NPCs haggle in words, and the game acts only when something really changes hands. One action, Trade, with the kind inside: give_gold, ask_gold, give_item, ask_item, offer_trade and take_gift (opens the game's gift menu). Anything you hand over asks you Yes/No first (not for an NPC flagged Trades without asking on the Hub's NPCs page). Followers, friends, lovers and anyone under an absolute command give and take freely; a stranger hands over gold or goods only as payment for what you gave them in the same talk. Only what the NPC really carries can be given, never quest items. Every trade checks that the gold or goods really arrived before anything leaves the other side; if the goods do not arrive, your gold comes back.
- Buying from merchants by talk: asking for one named item at a price ("sell me a torch for 5 gold") uses offer_trade, so you can haggle; "show me your wares" still opens the barter menu. A merchant is anyone in a shop faction with a merchant chest, wherever they stand: they sell from that chest, your gold goes into it, and the price is held to half to one and a half times the shop price. Anyone else is refused with a line. The barter menu keeps the game's own place and hours.
- Custom answer in the trade confirm box: type how much gold to hand over ("2000", "2,000" or "2000 gold"), another count of the item asked for, gold instead of the item ("50 gold"), or the price you pay a merchant (never under half the shop price). What really moves is what the NPC is told, so offering more than asked is a real surprise. You can never give more than you carry. Needs UIExtensions (a Mantella requirement); without it the box stays Yes / Not now.
- When you talk about buying, selling, gold or gifts, the NPCs here are told what they carry (gold and a few notable things). A merchant is told a few wares of each kind across prices (spell tomes and potions, not only soul gems and rings), how many more there are of each kind, and that the list is not complete, so he offers to check instead of saying he has none.
- Every action result goes back into the talk as an in-game event ("(Nothing happened: you have only 30 gold.)"), so the NPC knows whether it worked, and shows a short line on screen (switch: Action notifications, Hub MCM). A barter menu closed during a talk with that merchant is told to the talk.
- Killing or attacking a Thalmor: the people close by remember seeing it for 3 days, and a guard's crime report names the victim as Thalmor. Outside the big walled cities, and with no Thalmor or Legion soldier in the talk, they are told folk here do not much care. Bounties are not changed.
- Murders and attacks by you on ordinary people (not your party), and deaths of named people you did not kill, are kept for the Hub's world news: what happened, the day, the place with its town and hold, the victim and who was close by. One attack per person per day; a murder that day replaces it. Children are never listed as victims, and a child nearby is listed without a name.

### Changed
- With Mantella's Advanced Actions switched off, the trade kinds can no longer be triggered by keyword: Trade needs the kind, amount or item as a parameter. Only the gift menu still opens without them.
- The rule that gold and goods change hands only in the barter menu now names the trade actions too, and says that an offer that came to nothing never undoes something that already happened.
- SettleCrime and ReportWitnessedCrime show refusals on screen too, and follow the Action notifications switch.
- Quest scan: the full scan of quests no longer runs at every talk start. It runs after a save is loaded (a few seconds later; the saved values are written at once), after sleeping or waiting, and once a game day. Quest changes are picked up by the plugin and read in batches, at most once a minute. A scan that becomes due during a talk or a fight waits until it ends, and a request made while a scan runs is no longer dropped. Talk starts are faster.
- Trade action: a merchant sells a ware you ask for by name with offer_trade, at the shop price unless you agreed another, instead of opening the barter menu. The trade rule says a merchant also sells the shop's wares, not only what he carries.

### Fixed
- Settle a bounty and take a crime report are offered to Jarls and stewards too, as the actions always said. Needs the Integration Hub update.
- Trade refuses a negative amount, count or price, or one larger than can be traded at once, with a line in the talk. Before, a negative count became one item and a huge count became everything the NPC carried.
- The crime list waits for the other writer in steps the game keeps reliably, so two crimes logged at once both stay in the list.
- Fight accounts no longer carry over to another character loaded without restarting the game.
- Merchants: World now says whether it read the whole chest (it stops after 150 entries), so the Hub never calls a cut-off list the whole stock.
- After loading a save made while world.json was being refreshed, only one refresh runs (two could run at once).
- Whether a hood or helmet covers your face is now known before a talk starts, so the NPC's greeting already fits whether they recognise you.
- Fights: damage and kills count as yours only when you really attacked: a weapon or fist blow, or a spell you cast. An aura or cloak you carry no longer puts you down for damage and the kill in fights you never joined; such a kill is recorded with no killer.
- Ordinary dialogue: your topic is kept with a mod's own lines also when the game no longer holds your choice (most of a dialogue mod's lines had none).
- The hood line never names you to someone who does not recognise you: "the hooded stranger".
- Ordinary dialogue kept for one character never reaches another: each character keeps their own lines (other characters' are kept apart), and lines no talk used within 60 game days are dropped.
- Saving the kept ordinary dialogue no longer happens on the game's main thread, and the game's own files are not replaced while being read.
- A trap or stray arrow hitting you no longer starts a "the fight just ended" banter; banter looks for the party only when it will speak.
- An NPC who walked up to start a talk keeps their reason when that talk's end was missed and someone else spoke first.
- Two generic NPCs of one kind no longer share what they carry.
- A merchant joining a talk reads the shop chest once.
- world.json is never left marked as loading for the whole session.
- The separate trade actions of an earlier version are no longer listened for.

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

Scriptname MLWW_Facts Hidden
{Mantella Living World - World: game events as exact facts. The numbers are kept on the NPC in StorageUtil, so they
belong to the save; Sync turns them into fact_<name> values in MantellaLivingWorld/npc/<baseid>.json, which the
Integration Hub reads as "day|expires_day|priority|text" and dates itself. Without the Hub nobody reads them.
The file is not part of the save: Sync also removes a fact the current save has no numbers for. Only what happened
goes in the text, never how anyone should take it.}

; ---------------------------------------------------------------------------
; Records
; ---------------------------------------------------------------------------

; One barter menu: aiSpent gold the player paid, aiEarned gold the player was paid (both counted, not their balance).
Function Trade(Form akMerchant, int aiSpent, int aiEarned, bool abNewDay) global
	If aiEarned > 0
		StorageUtil.AdjustIntValue(akMerchant, "MLWW_SoldTotal", aiEarned)
	EndIf
	If aiSpent > 0
		StorageUtil.AdjustIntValue(akMerchant, "MLWW_SpentTotal", aiSpent)
	EndIf
	If abNewDay && (aiSpent > 0 || aiEarned > 0)
		StorageUtil.AdjustIntValue(akMerchant, "MLWW_Visits", 1)
	EndIf
EndFunction

; What the player sold in one barter menu; the eight most sold items are kept.
Function Goods(Form akMerchant, string asItem, int aiCount) global
	int at = StorageUtil.StringListFind(akMerchant, "MLWW_GoodsNames", asItem)
	If at >= 0
		StorageUtil.IntListAdjust(akMerchant, "MLWW_GoodsCounts", at, aiCount)
		Return
	EndIf
	If StorageUtil.StringListCount(akMerchant, "MLWW_GoodsNames") >= 8
		int least = GoodsAt(akMerchant, false)
		StorageUtil.StringListRemoveAt(akMerchant, "MLWW_GoodsNames", least)
		StorageUtil.IntListRemoveAt(akMerchant, "MLWW_GoodsCounts", least)
	EndIf
	StorageUtil.StringListAdd(akMerchant, "MLWW_GoodsNames", asItem)
	StorageUtil.IntListAdd(akMerchant, "MLWW_GoodsCounts", aiCount)
EndFunction

; Index of the most (or least) sold item, -1 when there are none.
int Function GoodsAt(Form akMerchant, bool abMost) global
	int best = -1
	int i = StorageUtil.IntListCount(akMerchant, "MLWW_GoodsCounts")
	While i > 0
		i -= 1
		int count = StorageUtil.IntListGet(akMerchant, "MLWW_GoodsCounts", i)
		If best < 0 || (abMost && count > StorageUtil.IntListGet(akMerchant, "MLWW_GoodsCounts", best)) || (!abMost && count < StorageUtil.IntListGet(akMerchant, "MLWW_GoodsCounts", best))
			best = i
		EndIf
	EndWhile
	Return best
EndFunction

; Adds one to a count and dates it today.
Function Count(Form akNpc, string asKey, string asDayKey) global
	StorageUtil.AdjustIntValue(akNpc, asKey, 1)
	StorageUtil.SetIntValue(akNpc, asDayKey, MLWW_Util.Today())
EndFunction

; One enemy beaten with akMember present. aiScore: level, + 1000 for a unique, + 2000 for a dragon.
Function Kill(Actor akMember, bool abByMember, bool abByPlayer, string asName, int aiScore) global
	If abByMember
		StorageUtil.AdjustIntValue(akMember, "MLWW_KillsOwn", 1)
	ElseIf abByPlayer
		StorageUtil.AdjustIntValue(akMember, "MLWW_KillsPlayer", 1)
	EndIf
	Best(akMember, asName, aiScore)
EndFunction

; Keeps the strongest enemy on akForm (None: the player's own, all party kills included).
Function Best(Form akForm, string asName, int aiScore) global
	If asName != "" && aiScore > StorageUtil.GetIntValue(akForm, "MLWW_BestScore", -1)
		StorageUtil.SetIntValue(akForm, "MLWW_BestScore", aiScore)
		StorageUtil.SetStringValue(akForm, "MLWW_BestName", asName)
		StorageUtil.SetIntValue(akForm, "MLWW_BestDay", MLWW_Util.Today())
	EndIf
EndFunction

; aiCleared dungeons counted at once, asName (may be "") the latest.
Function Dungeon(Actor akMember, string asName, int aiCleared) global
	StorageUtil.AdjustIntValue(akMember, "MLWW_Dungeons", aiCleared)
	StorageUtil.SetIntValue(akMember, "MLWW_DungeonDay", MLWW_Util.Today())
	StorageUtil.SetStringValue(akMember, "MLWW_DungeonLast", asName)
EndFunction

; Optional, for any module that keeps a score: asKind is deeds, care or gifts. Nothing happens when nobody listens.
Function Score(Form akNpc, string asKind, float afWeight) global
	int handle = ModEvent.Create("MLW_ScoreEvent")
	If handle
		ModEvent.PushForm(handle, akNpc)
		ModEvent.PushString(handle, asKind)
		ModEvent.PushFloat(handle, afWeight)
		ModEvent.Send(handle)
	EndIf
EndFunction

; ---------------------------------------------------------------------------
; The NPC's file
; ---------------------------------------------------------------------------

; Writes this NPC's facts from their numbers. The file is saved and the Hub told only when something changed.
; Three lines at most, each named once by the player: what the two did for and to each other, what they went through
; together, and trade. The Hub dates each line by its newest day.
Function Sync(Actor akNpc) global
	If !akNpc
		Return
	EndIf
	; The file is per base: generic guards, citizens and quartermasters share one, and the numbers are on each actor.
	; Writing them would move one stranger's facts onto the next (Personal.Line still gives them "today" lines).
	ActorBase base = akNpc.GetActorBase()
	If !base || !base.IsUnique()
		Return
	EndIf
	string path = "MantellaLivingWorld/npc/" + MLWW_Util.BaseId(akNpc) + ".json"
	string player = MLWW_Util.PlayerName()
	int careDay = Latest(Latest(DayOf(akNpc, "MLWW_SavedDay"), DayOf(akNpc, "MLWW_HealedDay")), DayOf(akNpc, "MLWW_HitDay"))
	int togetherDay = Latest(Latest(DayOf(akNpc, "MLWW_FoughtDay"), DayOf(akNpc, "MLWW_DefendedDay")), Latest(DayOf(akNpc, "MLWW_DungeonDay"), DayOf(akNpc, "MLWW_BestDay")))
	bool changed = Put(path, "fact_saved", careDay, 3, Care(akNpc, player))
	changed = Put(path, "fact_fought", togetherDay, 2, Together(akNpc, player)) || changed
	changed = Put(path, "fact_customer", -1, 1, Customer(akNpc, player)) || changed
	; Merged into the lines above: removed from files written by older versions.
	changed = Put(path, "fact_healed", -1, 1, "") || changed
	changed = Put(path, "fact_friendly_fire", -1, 1, "") || changed
	changed = Put(path, "fact_dungeons", -1, 1, "") || changed
	changed = Put(path, "fact_strongest", -1, 1, "") || changed
	changed = Put(path, "fact_strongest_player", -1, 1, "") || changed
	changed = Put(path, "fact_kills", -1, 1, "") || changed
	changed = Put(path, "fact_defended", -1, 1, "") || changed
	If changed
		JsonUtil.Save(path)
		int handle = ModEvent.Create("MLW_RefreshNpc")
		If handle
			ModEvent.PushForm(handle, akNpc)
			ModEvent.Send(handle)
		EndIf
	EndIf
EndFunction

; Sets or, with no text, removes a fact. True when that changed anything.
bool Function Put(string asPath, string asKey, int aiDay, int aiPriority, string asText) global
	string value = ""
	If asText != ""
		value = aiDay + "|-1|" + aiPriority + "|" + asText
	EndIf
	If value == JsonUtil.GetStringValue(asPath, asKey)
		Return false
	EndIf
	If value == ""
		JsonUtil.UnsetStringValue(asPath, asKey)
	Else
		JsonUtil.SetStringValue(asPath, asKey, value)
	EndIf
	Return true
EndFunction

int Function DayOf(Form akForm, string asKey) global
	Return StorageUtil.GetIntValue(akForm, asKey, -1)
EndFunction

int Function Latest(int aiA, int aiB) global
	If aiA > aiB
		Return aiA
	EndIf
	Return aiB
EndFunction

; ---------------------------------------------------------------------------
; The text. The Hub adds the date after it; only what happened, never how anyone should take it.
; ---------------------------------------------------------------------------

string Function Times(int aiCount) global
	If aiCount == 1
		Return "once"
	ElseIf aiCount == 2
		Return "twice"
	EndIf
	Return aiCount + " times"
EndFunction

; "they saved you 3 times, you saved them once": aiByPlayer times by the player, aiByNpc times by this NPC.
string Function Saves(int aiByPlayer, int aiByNpc) global
	string out = ""
	If aiByPlayer > 0
		out = "they saved you " + Times(aiByPlayer)
	EndIf
	If aiByNpc > 0
		If out != ""
			out += ", "
		EndIf
		out += "you saved them " + Times(aiByNpc)
	EndIf
	Return out
EndFunction

; "heals 12 to you, 3 to them": asWhat done aiToNpc times by the player and aiToPlayer times by this NPC.
string Function Counts(string asWhat, int aiToNpc, int aiToPlayer) global
	If aiToNpc <= 0 && aiToPlayer <= 0
		Return ""
	EndIf
	string out = asWhat
	If aiToNpc > 0
		out += " " + aiToNpc + " to you"
	EndIf
	If aiToNpc > 0 && aiToPlayer > 0
		out += ","
	EndIf
	If aiToPlayer > 0
		out += " " + aiToPlayer + " to them"
	EndIf
	Return out
EndFunction

; Parts joined with "; " after "With <player>: ", or "" when there are none.
string Function Join(string asPlayer, string[] akParts) global
	string out = ""
	int i = 0
	While i < akParts.Length
		If akParts[i] != ""
			If out != ""
				out += "; "
			EndIf
			out += akParts[i]
		EndIf
		i += 1
	EndWhile
	If out == ""
		Return ""
	EndIf
	Return "With " + asPlayer + ": " + out
EndFunction

; Rescues, heals and friendly hits both ways.
string Function Care(Actor akNpc, string asPlayer) global
	string[] parts = new string[3]
	parts[0] = Saves(StorageUtil.GetIntValue(akNpc, "MLWW_SavedByPlayer"), StorageUtil.GetIntValue(akNpc, "MLWW_SavedPlayer"))
	parts[1] = Counts("heals", StorageUtil.GetIntValue(akNpc, "MLWW_HealedByPlayer"), StorageUtil.GetIntValue(akNpc, "MLWW_HealedPlayer"))
	parts[2] = Counts("hits", StorageUtil.GetIntValue(akNpc, "MLWW_HitByPlayer"), StorageUtil.GetIntValue(akNpc, "MLWW_HitPlayer"))
	Return Join(asPlayer, parts)
EndFunction

string Function EnemyText(Form akForm) global
	string name = StorageUtil.GetStringValue(akForm, "MLWW_BestName")
	int score = StorageUtil.GetIntValue(akForm, "MLWW_BestScore", -1)
	If name == "" || score < 0
		Return ""
	ElseIf score >= 1000
		Return name
	EndIf
	Return name + " (level " + score + ")"
EndFunction

; Fights, enemies struck that were attacking the player, kills, dungeons and the strongest enemy faced together; for a
; party member also the strongest enemy the player has beaten, when that is stronger.
string Function Together(Actor akNpc, string asPlayer) global
	string[] parts = new string[5]
	int fights = StorageUtil.GetIntValue(akNpc, "MLWW_Fought")
	If fights == 1
		parts[0] = "1 fight"
	ElseIf fights > 1
		parts[0] = fights + " fights"
	EndIf
	int defended = StorageUtil.GetIntValue(akNpc, "MLWW_Defended")
	If defended > 0 && fights > 0
		parts[0] = parts[0] + ", defended them in " + defended
	ElseIf defended > 0
		parts[1] = "defended them " + Times(defended)
	EndIf
	int own = StorageUtil.GetIntValue(akNpc, "MLWW_KillsOwn")
	int theirs = StorageUtil.GetIntValue(akNpc, "MLWW_KillsPlayer")
	If own > 0 || theirs > 0
		parts[2] = "kills you " + own + ", them " + theirs
	EndIf
	int n = StorageUtil.GetIntValue(akNpc, "MLWW_Dungeons")
	string name = StorageUtil.GetStringValue(akNpc, "MLWW_DungeonLast")
	If n == 1 && name != ""
		parts[3] = "cleared " + name
	ElseIf n == 1
		parts[3] = "cleared a dungeon"
	ElseIf n > 1 && name != ""
		parts[3] = "cleared " + n + " dungeons, latest " + name
	ElseIf n > 1
		parts[3] = "cleared " + n + " dungeons"
	EndIf
	string mine = EnemyText(akNpc)
	string best = EnemyText(None)
	If best == "" || !akNpc.IsPlayerTeammate() || StorageUtil.GetIntValue(None, "MLWW_BestScore", -1) <= StorageUtil.GetIntValue(akNpc, "MLWW_BestScore", -1)
		best = ""
	EndIf
	If mine != "" && best != ""
		parts[4] = "strongest enemy " + mine + ", theirs " + best
	ElseIf mine != ""
		parts[4] = "strongest enemy " + mine
	ElseIf best != ""
		parts[4] = "their strongest enemy " + best
	EndIf
	Return Join(asPlayer, parts)
EndFunction

string Function Customer(Actor akNpc, string asPlayer) global
	int spent = StorageUtil.GetIntValue(akNpc, "MLWW_SpentTotal")
	int sold = StorageUtil.GetIntValue(akNpc, "MLWW_SoldTotal")
	If spent + sold < 50  ; a coin or two says nothing
		Return ""
	EndIf
	string line = asPlayer
	If spent > 0
		line += " spent ~" + Approx(spent) + " gold"
	EndIf
	If spent > 0 && sold > 0
		line += ","
	EndIf
	If sold > 0
		line += " sold you ~" + Approx(sold) + " in goods"
	EndIf
	int visits = StorageUtil.GetIntValue(akNpc, "MLWW_Visits")
	If visits > 1
		line += ", " + visits + " visits"
	EndIf
	int most = GoodsAt(akNpc, true)
	If most >= 0
		line += ", mostly " + StorageUtil.StringListGet(akNpc, "MLWW_GoodsNames", most)
	EndIf
	Return line
EndFunction

; 5,000 for 4,987: to the nearest 10 below a thousand, to the nearest 100 above ("~" says it is rounded).
string Function Approx(int aiGold) global
	If aiGold < 10
		Return aiGold  ; rounding would make it 0
	EndIf
	int step = 100
	If aiGold < 1000
		step = 10
	EndIf
	int n = (aiGold + step / 2) / step * step
	string out = ""
	While n >= 1000
		string part = n % 1000
		While StringUtil.GetLength(part) < 3
			part = "0" + part
		EndWhile
		out = "," + part + out
		n /= 1000
	EndWhile
	Return n + out
EndFunction

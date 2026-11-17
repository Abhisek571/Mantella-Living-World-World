Scriptname MLWW_Util Hidden
{Shared helpers for Mantella Living World - World.}

string Function HUB_PLUGIN() global
	Return "Mantella Living World - Integration Hub.esp"
EndFunction

; The Integration Hub, or None when it is not installed.
MLW_Hub Function Hub() global
	If Game.GetModByName(HUB_PLUGIN()) == 255 && Game.GetLightModByName(HUB_PLUGIN()) == 65535  ; the Hub is a light plugin
		Return None
	EndIf
	Return Game.GetFormFromFile(0x000820, HUB_PLUGIN()) as MLW_Hub
EndFunction

Function Log(string asText) global
	MLW_Hub hub = Hub()
	If hub
		hub.Log("world", asText)
	EndIf
EndFunction

; Sends one event line to the running Mantella conversation and keeps the last ten for the troubleshooting report.
Function Send(string asSource, string asLine) global
	If asLine == ""
		Return
	EndIf
	int handle = ModEvent.Create("MantellaAddEvent")
	If handle
		ModEvent.PushString(handle, asLine)
		ModEvent.Send(handle)
	EndIf
	StorageUtil.StringListAdd(None, "MLWW_Sent", asSource + ": " + asLine)
	While StorageUtil.StringListCount(None, "MLWW_Sent") > 10
		StorageUtil.StringListRemoveAt(None, "MLWW_Sent", 0)
	EndWhile
	Log(asSource + ": " + asLine)
EndFunction

; A short HUD line for what an action did, unless "Action notifications" is off in the Hub's MCM (MLW_ActionHud; an
; older Hub without it counts as on). Same switch as the Hub's MLW_Notify.Hud, read here so World needs no new Hub script.
Function Hud(string asText) global
	If asText == ""
		Return
	EndIf
	GlobalVariable on = None
	If Hub()
		on = Game.GetFormFromFile(0x00080D, HUB_PLUGIN()) as GlobalVariable
	EndIf
	If !on || on.GetValueInt() != 0
		Debug.Notification(asText)
	EndIf
EndFunction

; What an action did: a HUD line (Hud) and the same news for the NPCs in the talk as an in-game event line, so they know
; whether it worked. asSource names the job in the troubleshooting report.
Function Result(string asSource, string asHud, string asFact) global
	Hud(asHud)
	Send(asSource, asFact)
EndFunction

; Tells Mantella an action that requires a response has finished.
Function ActionDone(string asIdentifier) global
	int handle = ModEvent.Create("Mantella_ActionResponseCompleted")
	If handle
		ModEvent.PushString(handle, asIdentifier)
		ModEvent.Send(handle)
	EndIf
EndFunction

; Upper-case hex of the low aiDigits digits, zero padded.
string Function Hex(int aiValue, int aiDigits) global
	string digits = "0123456789ABCDEF"
	string out = ""
	int v = aiValue
	int i = 0
	While i < aiDigits
		out = StringUtil.GetNthChar(digits, Math.LogicalAnd(v, 0xF)) + out
		v = Math.RightShift(v, 4)
		i += 1
	EndWhile
	Return out
EndFunction

; The base id Mantella uses for an NPC (last six hex digits of the base form), as in npc/<baseid>.json.
string Function BaseId(Actor akActor) global
	; GetActorBase like the Hub: a leveled NPC's leveled base is a temporary form shared by unrelated people
	Return Hex(akActor.GetActorBase().GetFormID(), 6)
EndFunction

string Function Replace(string asText, string asFind, string asWith) global
	int flen = StringUtil.GetLength(asFind)
	If flen == 0
		Return asText
	EndIf
	string out = ""
	string rest = asText
	int at = StringUtil.Find(rest, asFind)
	While at >= 0
		If at > 0
			out += StringUtil.Substring(rest, 0, at)
		EndIf
		out += asWith
		If at + flen >= StringUtil.GetLength(rest)
			rest = ""
			at = -1
		Else
			rest = StringUtil.Substring(rest, at + flen)
			at = StringUtil.Find(rest, asFind)
		EndIf
	EndWhile
	Return out + rest
EndFunction

; A JSON string literal, quotes included.
string Function Quote(string asText) global
	Return "\"" + Replace(Replace(asText, "\\", "\\\\"), "\"", "\\\"") + "\""
EndFunction

; A JSON array of strings.
string Function QuoteAll(string[] akItems) global
	string out = "["
	int i = 0
	While akItems && i < akItems.Length
		If i > 0
			out += ","
		EndIf
		out += Quote(akItems[i])
		i += 1
	EndWhile
	Return out + "]"
EndFunction

string Function PlayerName() global
	Return Game.GetPlayer().GetDisplayName()
EndFunction

; Today as a whole game day.
int Function Today() global
	Return Utility.GetCurrentGameTime() as int
EndFunction

; ---------------------------------------------------------------------------
; Thalmor
; ---------------------------------------------------------------------------

; In the Thalmor (ThalmorFaction, Skyrim.esm 0x039F26).
bool Function IsThalmor(Actor akActor) global
	Faction thalmor = Game.GetFormFromFile(0x039F26, "Skyrim.esm") as Faction
	Return akActor && thalmor && akActor.IsInFaction(thalmor)
EndFunction

; Thalmor, or the Imperial Legion (CWImperialFaction, Skyrim.esm 0x02BF9A): company that minds harm to a Thalmor.
bool Function SidesWithThalmor(Actor akActor) global
	Faction legion = Game.GetFormFromFile(0x02BF9A, "Skyrim.esm") as Faction
	Return IsThalmor(akActor) || (akActor && legion && akActor.IsInFaction(legion))
EndFunction

; In one of the big walled cities (LocTypeCity: Whiterun, Solitude, Windhelm, Markarth, Riften), inside a building too.
bool Function InCity(Location akLocation) global
	Keyword city = Game.GetFormFromFile(0x013168, "Skyrim.esm") as Keyword
	Location here = akLocation
	int depth = 0
	While here && city && depth < 8
		If here.HasKeyword(city)
			Return true
		EndIf
		here = PO3_SKSEFunctions.GetParentLocation(here)
		depth += 1
	EndWhile
	Return false
EndFunction

; Harm the player did to a Thalmor, as one clause for a fact line: "the victim was Thalmor", plus "folk here do not much
; care" outside the big walled cities when neither akNpc nor anyone in the running talk is Thalmor or Legion (ordinary
; Nords and village folk have no love for the Thalmor and their Talos ban). Only words: bounties stay the game's.
string Function ThalmorClause(Actor akNpc) global
	If InCity(Game.GetPlayer().GetCurrentLocation()) || SidesWithThalmor(akNpc)
		Return "the victim was Thalmor"
	EndIf
	MantellaConversation talk = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as MantellaConversation
	If talk && talk.IsRunning()
		int i = talk.CountActorsInConversation()
		While i > 0
			i -= 1
			If SidesWithThalmor(talk.GetActorInConversationByIndex(i))
				Return "the victim was Thalmor"
			EndIf
		EndWhile
	EndIf
	Return "the victim was Thalmor, and folk here do not much care"
EndFunction

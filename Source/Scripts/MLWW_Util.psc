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

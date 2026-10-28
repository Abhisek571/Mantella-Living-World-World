Scriptname MLWW_Job extends Quest
{Base of every Mantella Living World - World quest. Register() runs from OnInit and again on every game load (the
quest's player alias calls it), so a save made before a registration existed still gets it.}

Actor Property PlayerRef Auto

Event OnInit()
	Register()
EndEvent

; Each job registers its mod events here. Safe to call any number of times.
Function Register()
EndFunction

; Called by the player alias on every location change.
Function LocationChanged(Location akOldLoc, Location akNewLoc)
EndFunction

; Called by the player alias when the player is hit.
Function PlayerHit()
EndFunction

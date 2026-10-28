Scriptname MLW_Pace Hidden
; Compile stub of the Integration Hub's pacing: only what this mod calls.
bool Function TryClaim(string asSource, float afCooldown) global
	Return false
EndFunction
string Function Blocked(string asSource, float afCooldown, float afNow) global
	Return ""
EndFunction
string Function ReportText() global
	Return ""
EndFunction
Function Reset() global
EndFunction

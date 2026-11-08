Scriptname MLWW_PlayerAlias extends ReferenceAlias
{Player alias on every World quest: re-registers the quest's events on each game load and passes location changes on. The banter quest
uses MLWW_BanterAlias, which also passes hits on.}

Event OnPlayerLoadGame()
	MLWW_Job job = GetOwningQuest() as MLWW_Job
	If job
		job.Register()
	EndIf
EndEvent

Event OnLocationChange(Location akOldLoc, Location akNewLoc)
	MLWW_Job job = GetOwningQuest() as MLWW_Job
	If job
		job.LocationChanged(akOldLoc, akNewLoc)
	EndIf
EndEvent

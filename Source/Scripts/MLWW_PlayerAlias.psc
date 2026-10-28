Scriptname MLWW_PlayerAlias extends ReferenceAlias
{Player alias on every World quest: re-registers the quest's events on each game load and passes location changes and hits on.}

Event OnPlayerLoadGame()
	MLWW_Job job = GetOwningQuest() as MLWW_Job
	If job
		job.Register()
	EndIf
EndEvent

Event OnHit(ObjectReference akAggressor, Form akSource, Projectile akProjectile, bool abPowerAttack, bool abSneakAttack, bool abBashAttack, bool abHitBlocked)
	MLWW_Job job = GetOwningQuest() as MLWW_Job
	If job
		job.PlayerHit()
	EndIf
EndEvent

Event OnLocationChange(Location akOldLoc, Location akNewLoc)
	MLWW_Job job = GetOwningQuest() as MLWW_Job
	If job
		job.LocationChanged(akOldLoc, akNewLoc)
	EndIf
EndEvent

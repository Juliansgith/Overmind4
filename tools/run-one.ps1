[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$Map = 'SCMP_007',

    [ValidateRange(0, 2147483647)]
    [int]$Seed = 7777,

    [ValidateRange(1, 100)]
    [int]$Speed = 25,

    [ValidateRange(1, 86400)]
    [int]$SimTime = 1800,

    [ValidateRange(1, 86400)]
    [int]$WallTime = 300,

    [ValidateRange(1, 10000)]
    [int]$UnitCap = 1000,

    [ValidateNotNullOrEmpty()]
    [string]$OurAI = 'overmind4',

    [ValidateNotNullOrEmpty()]
    [string]$OpponentAI = 'easy',

    [ValidateRange(1, 4)]
    [int]$OurFaction = 1,

    [ValidateRange(1, 4)]
    [int]$OpponentFaction = 1,

    [ValidateRange(1, 16)]
    [int]$OurSlot = 1,

    [ValidateRange(1, 16)]
    [int]$OpponentSlot = 2,

    [ValidateRange(1, 16)]
    [int]$OurTeam = 1,

    [ValidateRange(1, 16)]
    [int]$OpponentTeam = 2,

    [string]$OutputDirectory = 'artifacts/runs',

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot 'run_one.py'
$python = Get-Command 'py' -ErrorAction SilentlyContinue
$pythonArguments = @()

if ($python) {
    $pythonArguments += '-3'
} else {
    $python = Get-Command 'python' -ErrorAction Stop
}

$pythonArguments += @(
    $runner,
    '--map', $Map,
    '--seed', $Seed.ToString(),
    '--speed', $Speed.ToString(),
    '--sim-time', $SimTime.ToString(),
    '--wall-time', $WallTime.ToString(),
    '--unit-cap', $UnitCap.ToString(),
    '--our-ai', $OurAI,
    '--opponent-ai', $OpponentAI,
    '--our-faction', $OurFaction.ToString(),
    '--opponent-faction', $OpponentFaction.ToString(),
    '--our-slot', $OurSlot.ToString(),
    '--opponent-slot', $OpponentSlot.ToString(),
    '--our-team', $OurTeam.ToString(),
    '--opponent-team', $OpponentTeam.ToString(),
    '--output-dir', $OutputDirectory
)

if ($DryRun) {
    $pythonArguments += '--dry-run'
}

& $python.Source @pythonArguments
exit $LASTEXITCODE

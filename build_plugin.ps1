param(
    [string]$KspManagedDir = "D:\SteamLibrary\steamapps\common\Kerbal Space Program\KSP_x64_Data\Managed"
)

$ErrorActionPreference = "Stop"
$outDir = Join-Path $PSScriptRoot "GameData\ROPlanesPlus\Plugins"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) {
    throw "csc.exe not found at $csc"
}

& $csc /target:library /optimize+ /warn:4 /warnaserror+ `
  /out:"$outDir\ROPlanesPlus.dll" `
  /r:"$KspManagedDir\Assembly-CSharp.dll" `
  /r:"$KspManagedDir\UnityEngine.dll" `
  /r:"$KspManagedDir\UnityEngine.CoreModule.dll" `
  /r:"$KspManagedDir\UnityEngine.PhysicsModule.dll" `
  /r:"$KspManagedDir\UnityEngine.IMGUIModule.dll" `
  /r:"$KspManagedDir\UnityEngine.AnimationModule.dll" `
  /r:"$KspManagedDir\UnityEngine.AudioModule.dll" `
  /r:"$KspManagedDir\UnityEngine.TextRenderingModule.dll" `
  /r:"$KspManagedDir\UnityEngine.UI.dll" `
  /r:"$KspManagedDir\UnityEngine.ImageConversionModule.dll" `
  /r:"$KspManagedDir\UnityEngine.ParticleSystemModule.dll" `
  "$PSScriptRoot\Source\ROPlanesPlus\Properties\AssemblyInfo.cs" `
  "$PSScriptRoot\Source\ROPlanesPlus\Presets\PropellerPresets.cs" `
  "$PSScriptRoot\Source\ROPlanesPlus\Physics\PropellerPhysicsEngine.cs" `
  "$PSScriptRoot\Source\ROPlanesPlus\Physics\PerformanceModel.cs" `
  "$PSScriptRoot\Source\ROPlanesPlus\Physics\EngineStartSequence.cs" `
  "$PSScriptRoot\Source\ROPlanesPlus\Geometry\PropellerMeshGenerator.cs" `
  "$PSScriptRoot\Source\ROPlanesPlus\Modules\ModuleProceduralPropeller.cs" `
  "$PSScriptRoot\Source\ROPlanesPlus\Modules\ModuleEngineWorkshopButton.cs" `
  "$PSScriptRoot\Source\ROPlanesPlus\Geometry\PylonMeshGenerator.cs" `
  "$PSScriptRoot\Source\ROPlanesPlus\Modules\ModuleROPPLaunchPylon.cs" `
  "$PSScriptRoot\Source\ROPlanesPlus\Audio\PropellerAudio.cs" `
  "$PSScriptRoot\Source\ROPlanesPlus\Paint\CustomPaint.cs" `
  "$PSScriptRoot\Source\ROPlanesPlus\Effects\EngineEffects.cs" `
  "$PSScriptRoot\Source\ROPlanesPlus\UI\EngineWorkshopWindow.cs"

if ($LASTEXITCODE -ne 0) {
    throw "Compilation failed with exit code $LASTEXITCODE"
}

Write-Host "Built GameData/ROPlanesPlus/Plugins/ROPlanesPlus.dll ($((Get-Item "$outDir\ROPlanesPlus.dll").Length) bytes)"

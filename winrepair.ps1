# Repairs a 3MF file with Windows' built-in 3D printing repair (the one 3D Builder
# and the slicers' "fix model" use): Windows.Graphics.Printing3D, Printing3DModel.RepairAsync.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File winrepair.ps1 -In in.3mf -Out out.3mf
# Needs Windows PowerShell 5.1 (it reaches WinRT through .NET Framework).
param([Parameter(Mandatory)] [string]$In, [Parameter(Mandatory)] [string]$Out)
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Printing3D.Printing3D3MFPackage, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Printing3D.Printing3DModel, Windows.Graphics, ContentType = WindowsRuntime]

$ext = [System.WindowsRuntimeSystemExtensions].GetMethods()
$asTaskOp = $ext | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$asTaskAction = $ext | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1

function Await($op, [Type]$type) {
    $task = $asTaskOp.MakeGenericMethod($type).Invoke($null, @($op))
    $null = $task.Wait(-1)
    $task.Result
}
function AwaitAction($op) {
    $null = $asTaskAction.Invoke($null, @($op)).Wait(-1)
}

$inPath = [System.IO.Path]::GetFullPath($In)
$outPath = [System.IO.Path]::GetFullPath($Out)

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($inPath)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$package = Await ([Windows.Graphics.Printing3D.Printing3D3MFPackage]::LoadAsync($stream)) ([Windows.Graphics.Printing3D.Printing3D3MFPackage])
$model = Await ($package.LoadModelFromPackageAsync($stream)) ([Windows.Graphics.Printing3D.Printing3DModel])
$before = ($model.Meshes | Measure-Object -Property IndexCount -Sum).Sum  # IndexCount counts triangles

AwaitAction ($model.RepairAsync())
$after = ($model.Meshes | Measure-Object -Property IndexCount -Sum).Sum

# save into a fresh package: the one read from the file can refuse to save again
$fresh = New-Object Windows.Graphics.Printing3D.Printing3D3MFPackage
AwaitAction ($fresh.SaveModelToPackageAsync($model))
$saved = Await ($fresh.SaveAsync()) ([Windows.Storage.Streams.IRandomAccessStream])
$read = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($saved.GetInputStreamAt(0))
$dest = [System.IO.File]::Create($outPath)
try { $read.CopyTo($dest) } finally { $dest.Dispose(); $read.Dispose(); $stream.Dispose() }

# one JSON line for the caller
@{ ok = $true; meshes = @($model.Meshes).Length; triangles_before = [int]$before;
   triangles_after = [int]$after } | ConvertTo-Json -Compress

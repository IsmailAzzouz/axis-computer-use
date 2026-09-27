param([Parameter(Mandatory=$true)][string]$ImagePath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
$axisAsTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await-Axis($operation, $resultType) {
    $task = $axisAsTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
    if (-not $task.Wait(5000)) { throw 'OCR operation timeout' }
    $task.Result
}
$axisStream = $null
$axisBitmap = $null
try {
    $axisEngine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if (-not $axisEngine) { throw 'No OCR language installed' }
    $axisFile = Await-Axis ([Windows.Storage.StorageFile]::GetFileFromPathAsync([IO.Path]::GetFullPath($ImagePath))) ([Windows.Storage.StorageFile])
    $axisStream = Await-Axis ($axisFile.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $axisDecoder = Await-Axis ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($axisStream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $axisBitmap = Await-Axis ($axisDecoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $axisResult = Await-Axis ($axisEngine.RecognizeAsync($axisBitmap)) ([Windows.Media.Ocr.OcrResult])
    $axisLines = @($axisResult.Lines | ForEach-Object {
        @{text=$_.Text; words=@($_.Words | ForEach-Object {
            @{text=$_.Text; bounds=@([int]$_.BoundingRect.X, [int]$_.BoundingRect.Y, [int]($_.BoundingRect.X+$_.BoundingRect.Width), [int]($_.BoundingRect.Y+$_.BoundingRect.Height))}
        })}
    })
    $axisJson = @{text=$axisResult.Text; language=$axisEngine.RecognizerLanguage.LanguageTag; lines=$axisLines} | ConvertTo-Json -Depth 8 -Compress
    [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($axisJson))
} finally {
    if ($axisBitmap) { $axisBitmap.Dispose() }
    if ($axisStream) { $axisStream.Dispose() }
}

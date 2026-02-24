# pingpong.ps1
# Usage: .\pingpong.ps1 -input output_6.mp4 -loops 3
# Produces a seamless looping video by appending forward + reverse N times.
#
# Examples:
#   .\pingpong.ps1 -input output_6.mp4              # 1 pingpong (forward+reverse)
#   .\pingpong.ps1 -input output_6.mp4 -loops 3     # 3 pingpongs
#   .\pingpong.ps1 -input output_6.mp4 -loops 3 -out my_result.mp4

param(
    [Parameter(Mandatory=$true)]
    [string]$src,

    [int]$loops = 1,

    [string]$out = ""
)

# Resolve to absolute path
$src = Resolve-Path $src

# Resolve output filename
if ($out -eq "") {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($src)
    $out = Join-Path (Split-Path $src) "${base}_loop${loops}.mp4"
}

# Build the ffmpeg filter: forward + reverse, repeated $loops times
# e.g. loops=2 → [0][r][0][r] concat=n=4
$filterParts = @()
$concatInputs = ""
$n = $loops * 2  # each loop = forward + reverse

for ($i = 0; $i -lt $loops; $i++) {
    $filterParts += "[0]reverse[r$i]"
    $concatInputs += "[0][r$i]"
}

$filter = ($filterParts -join ";") + ";" + $concatInputs + "concat=n=${n}:v=1:a=0[out]"

Write-Host ""
Write-Host "  Input  : $src"
Write-Host "  Output : $out"
Write-Host "  Loops  : $loops pingpong(s) = $n segments"
Write-Host ""

ffmpeg -y -i "$src" -filter_complex $filter -map "[out]" "$out"

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Done! Saved to: $out"
} else {
    Write-Host ""
    Write-Host "ffmpeg failed with exit code $LASTEXITCODE"
}
